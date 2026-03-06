import requests
from bs4 import BeautifulSoup
import re
import os
from openai import OpenAI
import json

def translate_title(title, client):
    """调用 AI 接口翻译标题"""
    try:
        response = client.chat.completions.create(
            model="ecnu-plus",
            messages=[
                {"role": "system", "content": "你是一个专业的科技新闻翻译人员。请将给定的英文科技新闻标题翻译成地道流畅的中文。只返回翻译后的文本，不要包含任何多余的解释。"},
                {"role": "user", "content": title}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[翻译失败: {e}]"

def send_to_feishu(results, webhook_url):
    """将结果推送到飞书群机器人（每5条分割为一条消息）"""
    if not results:
        return

    batch_size = 5
    total = len(results)
    
    for batch_index in range(0, total, batch_size):
        batch = results[batch_index : batch_index + batch_size]
        post_elements = []
        
        for local_i, item in enumerate(batch):
            i = batch_index + local_i + 1
            en_title = item.get("english_title", "")
            zh_title = item.get("chinese_translation", "")
            link = item.get("link", "")
            
            display_title = zh_title if zh_title and not zh_title.startswith("[翻译失败:") else en_title
            
            post_elements.append([
                {"tag": "text", "text": f"{i}. "},
                {"tag": "a", "text": display_title, "href": link}
            ])
            if display_title != en_title:
                 post_elements.append([{"tag": "text", "text": f"   原文: {en_title}"}])
                 
            # 添加一个空段落，保证两条新闻之间有空白行分隔，增加易读性
            post_elements.append([{"tag": "text", "text": ""}])
                 
        start_idx = batch_index + 1
        end_idx = batch_index + len(batch)
        title_suffix = f" (第 {start_idx}-{end_idx} 条，共 {total} 条)"
        
        payload = {
            "msg_type": "post",
            "content": {"post": {"zh_cn": {"title": f"🤖 每日Techmeme AI 前沿资讯{title_suffix}", "content": post_elements}}}
        }

        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            print(f"\n✅ 成功推送到飞书 ({start_idx}-{end_idx})！响应: {response.text}")
        except Exception as e:
            print(f"\n❌ 推送飞书失败 ({start_idx}-{end_idx}): {e}")

def scrape_techmeme_ai_news():
    url = "https://techmeme.com/"
    # 添加 User-Agent 防止被网站当做 bot 直接拒绝
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 初始化 OpenAI 客户端
    api_key = os.environ.get("OPENAI_API_KEY")
    client = None
    if not api_key:
        print("⚠️ 未检测到 OPENAI_API_KEY 环境变量，将跳过中文翻译。您可以执行 `export OPENAI_API_KEY='your_key'` 来设置。\n")
    else:
        # 使用华东师大 ECNU 接口
        client = OpenAI(
            api_key=api_key,
            base_url="https://chat.ecnu.edu.cn/open/api/v1",
        )

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"❌ 访问 Techmeme 失败: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Techmeme 的主要新闻标题通常带有 'ourh' class，或者存在于特定结构中
    # 这里抓取带有 'ourh' 类的 a 标签，如果网站结构更新，可能需要调整 class
    headlines = soup.find_all('a', class_='ourh')
    
    # 如果没找到，退化为查找所有的重要标题(Techmeme 特色的 strong a)
    if not headlines:
        strong_tags = soup.find_all('strong')
        headlines = [strong.find('a') for strong in strong_tags if strong.find('a')]

    # 定义 AI 相关的关键词（不区分大小写）
    ai_keywords = [
        r'\bai\b', 'artificial intelligence', 'chatgpt', 'openai', 
        'anthropic', 'claude', 'gemini', r'\bllm\b', 'machine learning',
        'copilot', 'midjourney', 'sam altman', 'deepmind'
    ]
    
    print("🤖 正在从 Techmeme 获取 AI 资讯...\n" + "="*40)
    
    found_links = set()
    results = [] # 保存结果的列表
    count = 0
    
    for item in headlines:
        if not item:
            continue
            
        title = item.get_text(strip=True)
        link = item.get('href')
        
        if not title or not link or not link.startswith('http'):
            continue
            
        title_lower = title.lower()
        
        # 检查标题中是否包含 AI 相关的关键词
        is_ai_news = False
        for kw in ai_keywords:
            if re.search(kw, title_lower):
                is_ai_news = True
                break
                
        if is_ai_news and link not in found_links:
            count += 1
            found_links.add(link)
            
            # 使用 AI 接口翻译标题
            zh_translation = ""
            if client:
                print(f"🔄 正在翻译第 {count} 条资讯...")
                zh_translation = translate_title(title, client)
            
            # 组装字典
            news_item = {
                "english_title": title,
                "chinese_translation": zh_translation,
                "link": link
            }
            results.append(news_item)
            
    if count == 0:
        print("未找到近期的 AI 相关新闻。")
    else:
        print(f"\n✅ 共处理完成 {count} 条 AI 相关资讯。")
        print("👇 结果展示如下 👇")
        print("="*40)
        # 美观地输出 JSON 格式
        print(json.dumps(results, indent=4, ensure_ascii=False))
        
        # 尝试推送到飞书
        feishu_webhook = os.environ.get("FEISHU_WEBHOOK")
        if feishu_webhook:
            print("🔄 检测到飞书 Webhook 环境变量，正在尝试推送...")
            send_to_feishu(results, feishu_webhook)
        else:
            print("ℹ️ 未检测到 FEISHU_WEBHOOK 环境变量，不在飞书进行推送。")

if __name__ == "__main__":
    scrape_techmeme_ai_news()


