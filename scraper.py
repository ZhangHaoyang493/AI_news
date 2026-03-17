import requests
import os
import re
from openai import OpenAI
import json
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_translate_config():
    """根据开关生成翻译配置"""
    provider = os.environ.get("TRANSLATE_PROVIDER", "deepseek").strip().lower()
    if provider == "ecnu":
        return {
            "provider": "ecnu",
            "api_key": os.environ.get("ECNU_API_KEY"),
            "model_name": "ecnu-plus",
            "base_url": "https://chat.ecnu.edu.cn/open/api/v1/chat/completions"
        }
    return {
        "provider": "deepseek",
        "api_key": os.environ.get("DEEPSEEK_API_KEY"),
        "model_name": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1"
    }

def translate_title(title, client, model_name, provider, base_url, api_key):
    """调用 AI 接口翻译标题"""
    try:
        messages = [
            {"role": "system", "content": "你是一个专业的科技新闻翻译人员。请将给定的英文科技新闻标题翻译成地道流畅的中文。只返回翻译后的文本，不要包含任何多余的解释。"},
            {"role": "user", "content": title}
        ]

        if provider == "ecnu":
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.3
            }
            response = requests.post(base_url, headers=headers, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[翻译失败: {e}]"

def summarize_text(raw_text, client, model_name, provider, base_url, api_key, source_type):
    """调用 AI 接口生成摘要"""
    if not raw_text:
        return "获取新闻源信息失败（内容为空）"
    try:
        source_hint = "新闻原文" if source_type == "article" else "Hacker News 讨论"
        messages = [
            {"role": "system", "content": "你是科技新闻编辑。请基于给定内容输出简洁中文摘要（2-4句），聚焦核心事实、结论与影响。不要编造。"},
            {"role": "user", "content": f"内容来源：{source_hint}\n\n请总结以下内容：\n{raw_text[:5000]}"}
        ]

        if provider == "ecnu":
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.3
            }
            response = requests.post(base_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"获取新闻源信息失败（摘要生成失败: {e}）"

def fetch_article_content(url):
    """抓取原网站正文文本"""
    if not url or not url.startswith("http"):
        return ""
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.extract()
        text = soup.get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()[:8000]
    except Exception:
        return ""

def fetch_hn_discussion_content(hn_url):
    """抓取 HN 讨论文本（Algolia Items API）"""
    if not hn_url:
        return ""
    match = re.search(r"id=(\d+)", hn_url)
    if not match:
        return ""
    item_id = match.group(1)
    try:
        data = requests.get(f"https://hn.algolia.com/api/v1/items/{item_id}", timeout=10).json()
        comments = []

        def walk(node):
            html_text = node.get("text") or ""
            if html_text:
                clean = BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True)
                clean = re.sub(r"\s+", " ", clean).strip()
                if clean:
                    comments.append(clean)
            for child in node.get("children", []):
                walk(child)

        walk(data)
        return " ".join(comments)[:8000]
    except Exception:
        return ""

def build_summary(link, hn_url, client, model_name, provider, base_url, api_key):
    """优先总结原文，失败时回退总结 HN 讨论"""
    article_text = fetch_article_content(link)
    if article_text:
        return summarize_text(article_text, client, model_name, provider, base_url, api_key, "article"), "原文"

    hn_text = fetch_hn_discussion_content(hn_url)
    if hn_text:
        return summarize_text(hn_text, client, model_name, provider, base_url, api_key, "hn_discussion"), "HN讨论"

    return "获取新闻源信息失败（原文与 HN 讨论均不可用）", "失败"

def is_balance_related_error(error_text):
    """判断翻译失败是否与余额/配额不足相关"""
    if not error_text:
        return False

    text = error_text.lower()
    balance_patterns = [
        "insufficient",
        "insufficient_quota",
        "quota",
        "balance",
        "credit",
        "额度",
        "余额",
        "配额",
        "欠费",
        "用尽"
    ]
    return any(pattern in text for pattern in balance_patterns)

def send_to_feishu(results, webhook_url):
    """将结果推送到飞书群机器人（每5条分割为一条消息）"""
    if not results:
        return

    failed_items = [
        item for item in results
        if item.get("chinese_translation", "").startswith("[翻译失败:")
    ]
    balance_failed_count = sum(
        1 for item in failed_items if is_balance_related_error(item.get("chinese_translation", ""))
    )

    batch_size = 5
    total = len(results)
    # 获取北京时间
    beijing_tz = timezone(timedelta(hours=8))
    current_time = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M")
    
    for batch_index in range(0, total, batch_size):
        batch = results[batch_index : batch_index + batch_size]
        post_elements = []

        if batch_index == 0 and failed_items:
            if balance_failed_count > 0:
                post_elements.append([{
                    "tag": "text",
                    "text": f"⚠️ 翻译预警：检测到 {balance_failed_count} 条疑似因 DeepSeek token 余额/配额不足导致翻译失败，请尽快检查账户余额。"
                }])
            else:
                post_elements.append([{
                    "tag": "text",
                    "text": f"⚠️ 翻译预警：检测到 {len(failed_items)} 条翻译失败，请检查 DeepSeek 服务状态、模型权限或 API 配置。"
                }])
            post_elements.append([{"tag": "text", "text": ""}])
        
        for local_i, item in enumerate(batch):
            i = batch_index + local_i + 1
            en_title = item.get("english_title", "")
            zh_title = item.get("chinese_translation", "")
            link = item.get("link", "")
            source = item.get("source", "")
            hn_url = item.get("hn_url", "")
            heat = item.get("heat", "")
            time_str = item.get("time", "")
            summary = item.get("summary", "")
            summary_source = item.get("summary_source", "")
            
            display_title = zh_title if zh_title and not zh_title.startswith("[翻译失败:") else en_title
            
            post_elements.append([
                {"tag": "text", "text": f"{i}. "},
                {"tag": "a", "text": display_title, "href": link}
            ])
            post_elements.append([{"tag": "text", "text": f"   原文标题: {en_title}"}])
            if source or heat or time_str:
                post_elements.append([{"tag": "text", "text": f"   来源: {source} | 热度🔥: {heat} | 时间🕙: {time_str}"}])
            if link:
                post_elements.append([{"tag": "a", "text": "   原文链接", "href": link}])
            if hn_url:
                post_elements.append([{"tag": "a", "text": "   Hacker News 讨论", "href": hn_url}])
            if summary:
                if summary_source:
                    post_elements.append([{"tag": "text", "text": f"   摘要来源: {summary_source}"}])
                post_elements.append([{"tag": "text", "text": f"   摘要: {summary}"}])
                 
            # 添加一个空段落，保证两条新闻之间有空白行分隔，增加易读性
            post_elements.append([{"tag": "text", "text": ""}])
                 
        start_idx = batch_index + 1
        end_idx = batch_index + len(batch)
        title_suffix = f" [{current_time}] (第 {start_idx}-{end_idx} 条，共 {total} 条)"
        
        payload = {
            "msg_type": "post",
            "content": {"post": {"zh_cn": {"title": f"🤖 每日 Hacker News AI 前沿资讯{title_suffix}", "content": post_elements}}}
        }

        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            print(f"\n✅ 成功推送到飞书 ({start_idx}-{end_idx})！响应: {response.text}")
        except Exception as e:
            print(f"\n❌ 推送飞书失败 ({start_idx}-{end_idx}): {e}")

def filter_items(items, keyword=None):
    """与 fetch_news.py 保持一致的关键词过滤逻辑"""
    if not keyword:
        return items
    keywords = [k.strip() for k in keyword.split(',') if k.strip()]
    pattern = '|'.join([r'\b' + re.escape(k) + r'\b' for k in keywords])
    regex = r'(?i)(' + pattern + r')'
    return [item for item in items if re.search(regex, item['title'])]

def fetch_hackernews_same_as_fetch_news(limit=10, keyword=None):
    """复用 fetch_news.py 的 Hacker News 抓取口径"""
    if keyword:
        try:
            timestamp_24h = int(time.time() - 24 * 3600)
            raw_keywords = [k.strip() for k in keyword.split(',')]
            quoted_keywords = [f'"{k}"' if ' ' in k else k for k in raw_keywords]
            query_str = " OR ".join(quoted_keywords)

            api_url = f"http://hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=created_at_i>{timestamp_24h}&hitsPerPage={limit*2}&query={requests.utils.quote(query_str)}"
            data = requests.get(api_url, timeout=10).json()
            hits = data.get('hits', [])

            if not hits and raw_keywords:
                simple_query = raw_keywords[0]
                api_url_simple = f"http://hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=created_at_i>{timestamp_24h}&hitsPerPage={limit*2}&query={requests.utils.quote(simple_query)}"
                data = requests.get(api_url_simple, timeout=10).json()
                hits = data.get('hits', [])

            items = []
            for hit in hits:
                items.append({
                    "source": "Hacker News",
                    "title": hit.get('title'),
                    "url": hit.get('url') or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    "hn_url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    "heat": f"{hit.get('points', 0)} points",
                    "time": "Today"
                })
            return items[:limit]
        except Exception:
            pass

    base_url = "https://news.ycombinator.com"
    news_items = []
    page = 1
    max_pages = 5

    while len(news_items) < limit and page <= max_pages:
        url = f"{base_url}/news?p={page}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                break
        except Exception:
            break

        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.select('.athing')
        if not rows:
            break

        page_items = []
        for row in rows:
            try:
                id_ = row.get('id')
                title_line = row.select_one('.titleline a')
                if not title_line:
                    continue
                title = title_line.get_text()
                link = title_line.get('href')

                score_span = soup.select_one(f'#score_{id_}')
                score = score_span.get_text() if score_span else "0 points"

                age_span = soup.select_one(f'.age a[href="item?id={id_}"]')
                time_str = age_span.get_text() if age_span else ""

                if link and link.startswith('item?id='):
                    link = f"{base_url}/{link}"

                page_items.append({
                    "source": "Hacker News",
                    "title": title,
                    "url": link,
                    "hn_url": f"{base_url}/item?id={id_}",
                    "heat": score,
                    "time": time_str
                })
            except Exception:
                continue

        news_items.extend(filter_items(page_items, keyword))
        if len(news_items) >= limit:
            break
        page += 1
        time.sleep(0.5)

    return news_items[:limit]

def scrape_hackernews_ai_news():
    limit = int(os.environ.get("HACKERNEWS_LIMIT", "20"))

    translate_cfg = get_translate_config()
    provider = translate_cfg["provider"]
    api_key = translate_cfg["api_key"]
    model_name = translate_cfg["model_name"]
    base_url = translate_cfg["base_url"]
    client = None

    if not api_key:
        missing_key = "DEEPSEEK_API_KEY" if provider == "deepseek" else "ECNU_API_KEY"
        print(f"⚠️ 未检测到 {missing_key} 环境变量，将跳过中文翻译。\n")
    else:
        print(f"ℹ️ 当前翻译提供方: {provider}，模型: {model_name}，接口地址: {base_url}")
        if provider == "deepseek":
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
            )

    print("🤖 正在按 fetch_news.py 口径获取 Hacker News 资讯...\n" + "="*40)
    raw_items = fetch_hackernews_same_as_fetch_news(limit=limit, keyword=None)
    if not raw_items:
        print("未获取到 Hacker News 资讯。")
        return

    results = [] # 保存结果的列表

    for idx, item in enumerate(raw_items, start=1):
        title = item.get("title", "")
        link = item.get("url", "")
        if not title or not link:
            continue

        zh_translation = ""
        if api_key and (provider == "ecnu" or client):
            print(f"🔄 正在翻译第 {idx} 条资讯...")
            zh_translation = translate_title(title, client, model_name, provider, base_url, api_key)

        summary = "获取新闻源信息失败（未配置模型）"
        summary_source = "失败"
        if api_key and (provider == "ecnu" or client):
            print(f"📝 正在生成第 {idx} 条摘要...")
            summary, summary_source = build_summary(
                link=link,
                hn_url=item.get("hn_url", ""),
                client=client,
                model_name=model_name,
                provider=provider,
                base_url=base_url,
                api_key=api_key
            )

        news_item = {
            "english_title": title,
            "chinese_translation": zh_translation,
            "link": link,
            "source": item.get("source", "Hacker News"),
            "hn_url": item.get("hn_url", ""),
            "heat": item.get("heat", ""),
            "time": item.get("time", ""),
            "summary": summary,
            "summary_source": summary_source
        }
        results.append(news_item)

    if not results:
        print("未获取到可处理的资讯。")
        return

    print(f"\n✅ 共处理完成 {len(results)} 条 Hacker News 资讯。")
    print("👇 结果展示如下 👇")
    print("="*40)
    print(json.dumps(results, indent=4, ensure_ascii=False))
    
    # 尝试推送到飞书
    feishu_webhook = os.environ.get("FEISHU_WEBHOOK")
    if feishu_webhook:
        print("🔄 检测到飞书 Webhook 环境变量，正在尝试推送...")
        send_to_feishu(results, feishu_webhook)
    else:
        print("ℹ️ 未检测到 FEISHU_WEBHOOK 环境变量，不在飞书进行推送。")

if __name__ == "__main__":
    scrape_hackernews_ai_news()
