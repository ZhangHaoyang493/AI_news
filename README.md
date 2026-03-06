# Techmeme AI News Scraper

这是一个简单的 Python 爬虫，用于快速抓取 [Techmeme](https://techmeme.com/) 首页上与 AI（人工智能、大模型等）相关的最新重点资讯。

## 使用 GitHub Actions 每日自动推送到飞书

我们目前已经配置好了 GitHub Actions 工作流(`.github/workflows/daily_news.yml`)，它会在每天中国北京时间下午 13:00（UTC时间 5:00）自动运行。如果您想启用它推送到飞书，只需按照以下步骤设置：

### 1. 将项目推送到您的 GitHub 个人仓库
```bash
git init
git add .
git commit -m "init AI scraper"
# 链接您在 GitHub 创建好的空白 Repo
git remote add origin https://github.com/<您的用户名>/<您的repo名称>.git
git push -u origin master
```

### 2. 获取飞书自定义机器人 Webhook
1. 在飞书群聊设置中，找到 **“群机器人”**。
2. 点击 **“添加机器人”** -> 选择 **“自定义机器人”**。
3. 随意起名字（如 "AI 前沿速递"）然后点击添加。
4. 复制生成的 **Webhook URL**。

### 3. 在 GitHub 仓库设置 Secrets 密钥变量
1. 打开您的 GitHub 仓库页面，点击上方的 **Settings** 选项卡。
2. 在左侧菜单栏展开 **Secrets and variables**，点击 **Actions**。
3. 点击 **New repository secret** 按钮。
4. 创建第一个 Secret 存放 AI 翻译的 Key：
   - Name: `OPENAI_API_KEY`
   - Secret: `your_api_key`
5. 创建第二个 Secret 存放飞书的推送地址：
   - Name: `FEISHU_WEBHOOK`
   - Secret: `之前复制的飞书Webhook URL`

完成配置后，Action 就能够自动抓取资讯、翻译并在每天下午 1 点将新鲜结果直接发在您的飞书群里啦！您也可以在 GitHub的 "Actions" 页面手动点击 "Run workflow" 测试一次。

---

## 本地依赖包

- `requests`
- `beautifulsoup4`
- `openai` (用于将英文标题翻译为中文)

## 使用 `uv` 搭建环境并运行

本项目推荐使用 [uv](https://github.com/astral-sh/uv) —— 一个由 Rust 编写的极速 Python 包和环境管理器，来创建和管理虚拟环境。

### 1. 配置环境变量 (可选，用于 AI 翻译)

如果在翻译功能中您想要使用 OpenAI 的大语言模型对抓取到的资讯进行英译中操作，请先在终端中设置好 API Key 环境变量：

- **macOS / Linux**:
  ```bash
  export OPENAI_API_KEY="您的_API_KEY"
  ```
- **Windows (PowerShell)**:
  ```powershell
  $env:OPENAI_API_KEY="您的_API_KEY"
  ```
> 💡 *提示：如果不配置该环境变量，爬虫将跳过翻译功能，只保留空字符串的占位符。*

### 2. 创建虚拟环境

在项目根目录下（包含 `scraper.py` 的目录），运行以下命令创建一个新的虚拟环境：

```bash
uv venv
```

这会在当前目录下生成一个名为 `.venv` 的文件夹。

### 2. 激活虚拟环境

- **macOS / Linux**:
  ```bash
  source .venv/bin/activate
  ```
- **Windows**:
  ```bash
  .venv\Scripts\activate
  ```

激活后，你的命令行提示符前通常会出现 `(.venv)` 字样。

### 4. 安装依赖

使用 `uv pip` 命令极速安装项目所需的依赖包：

```bash
uv pip install requests beautifulsoup4 openai
```

### 5. 运行爬虫

环境准备就绪后，直接运行脚本：

```bash
python scraper.py
```

---

### 💡 进阶使用：单行命令运行 (uv run)

如果你不想手动激活环境和安装依赖，`uv` 支持直接声明临时依赖并运行脚本：

```bash
uv run --with requests --with beautifulsoup4 --with openai scraper.py
```
这会在隔离的环境中自动获取依赖并执行代码！
