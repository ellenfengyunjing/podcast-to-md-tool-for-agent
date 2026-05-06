# Podcast Knowledge Agent

把任何播客 URL 交给 AI 编程 Agent（Claude Code / OpenClaw / Codex / Claude Desktop …），Agent 自动调用本工具完成：**下载 → 转写 → 结构化文本**，输出可直接阅读、引用、二次编辑的转录数据。

**一句话定位**：本工具只负责“把音频变成高质量结构化文字”，摘要 / 分析 / 改写这些工作由调用它的 Agent 自己的大模型来做——因此你**不需要为本工具单独配置 LLM**。

## 功能特性

- **MCP 原生**：作为 MCP Server 暴露给 Agent，Agent 识别到用户给的播客 URL（或自己搜到的 URL）会自动调用。
- **一个 Key 就够用**：默认路径只需要 `PKA_GROQ_API_KEY`（Groq 免费额度 8 小时 / 天）。
- **多平台解析**：Apple Podcasts、小宇宙（Xiaoyuzhou FM）、YouTube、任意 RSS/Atom Feed、任意直链音频（MP3 / M4A / WAV / OGG）。
- **极速转写**：Groq Whisper API，30 分钟音频约 2 分钟完成；多块并行；自带标点、时间戳、中英日等 50+ 语言。
- **Agent-ready 输出**：全文 + 按分钟分段的段落 + 带时间戳的逐句 segments + 元数据，便于 Agent 摘要、引用、做笔记。
- **可选 LLM 流水线**：想要一条龙（转写 + 摘要 + Agent 记忆块），再额外配置 `PKA_LLM_API_KEY` 即可启用 `extract_knowledge` 工具。

## 架构（agent-driven 模式）

```
[Agent 对话]
   │
   │  用户："帮我看看这个播客讲了什么 <url>"
   │  或：Agent 自主搜索后得到播客 URL
   ▼
[MCP 调用 transcribe_podcast(url)]
   │
   ▼
[本工具]  resolve → download → chunk → Groq ASR → 结构化 JSON
   │
   ▼
[Agent 用自己的 LLM 读转录文本，完成摘要/分析/编辑]
```

## 快速开始（Claude Code / Codex / OpenClaw）

### 1. 安装依赖

```bash
git clone https://github.com/ellenfengyunjing/podcast-to-md-tool-for-agent.git
cd podcast-to-md-tool-for-agent

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -e .
```

### 2. 拿一个免费 Groq Key

https://console.groq.com （无需信用卡，每天 ~8h 免费转写额度）

### 3. 把本工具注册给 Agent

#### Claude Code（推荐）

```bash
claude mcp add podcast-knowledge -- python -m src.mcp_server \
  -e PKA_GROQ_API_KEY=gsk_your-groq-key-here
```

> Windows PowerShell 记得把 `\` 换成反引号 `` ` `` 或写成一行。

#### OpenClaw

在 `.openclaw/mcp.json`（或项目根的 `mcp.json`）里加：

```json
{
  "mcpServers": {
    "podcast-knowledge": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/absolute/path/to/podcast-to-md-tool-for-agent",
      "env": { "PKA_GROQ_API_KEY": "gsk_your-groq-key-here" }
    }
  }
}
```

#### Codex / 其他 MCP Client

同样使用 stdio 启动命令 `python -m src.mcp_server`，传入环境变量 `PKA_GROQ_API_KEY`。

#### Claude Desktop

编辑 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "podcast-knowledge": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/absolute/path/to/podcast-to-md-tool-for-agent",
      "env": { "PKA_GROQ_API_KEY": "gsk_your-groq-key-here" }
    }
  }
}
```

### 4. 直接对 Agent 说话

配好之后，Agent 就会自动触发：

> 「把这期小宇宙转成文字：https://www.xiaoyuzhoufm.com/episode/...」
>
> 「听一下这期 Apple Podcasts 讲了啥：https://podcasts.apple.com/cn/podcast/xxx/id1234?i=1000611...」
>
> 「帮我搜一个关于 AI 产品设计的中文播客，然后把内容整理成 markdown」
>
> 「把这集 YouTube 视频的音频转成会议纪要：https://youtu.be/...」

Agent 会调用 `transcribe_podcast(url)` 获得结构化转写文本，然后用自己的模型做摘要、整理要点、生成表格、转成 Markdown 笔记等任何后续工作。

## MCP 工具清单

| 工具 | 何时使用 | 是否需要 LLM Key |
|------|----------|------------------|
| `transcribe_podcast(url, language?)` | **默认工具**。Agent 自己会做摘要/分析时用它。 | 否（只需 Groq） |
| `extract_knowledge(url, language?)` | 非 Agent 调用（脚本、定时任务）想要开箱即用的摘要 + Agent 记忆块。 | 是（需 `PKA_LLM_API_KEY`） |

仅当检测到 `PKA_LLM_API_KEY` 时，`extract_knowledge` 才会出现在工具列表里——这样 Agent 不会被多余的工具干扰。

## `transcribe_podcast` 输出格式

```json
{
  "job_id": "mcp-20260506-101520",
  "source": {
    "url": "https://www.xiaoyuzhoufm.com/episode/...",
    "platform": "xiaoyuzhou",
    "title": "节目标题",
    "author": "主播名",
    "duration_seconds": 1748.7,
    "published_at": "2026-05-01",
    "thumbnail_url": "https://...",
    "description": "节目简介"
  },
  "transcript": {
    "full_text": "完整转录文本，已含标点符号……",
    "paragraphs": [
      { "time_range": "00:00 - 01:00", "time_start": 0.0, "time_end": 60.0, "text": "……" },
      { "time_range": "01:00 - 02:00", "time_start": 60.0, "time_end": 120.0, "text": "……" }
    ],
    "segments": [
      { "start": 0.0, "end": 5.2, "text": "……", "speaker": "SPEAKER_00" }
    ],
    "segment_count": 312
  },
  "processing": {
    "asr_model": "groq/whisper-large-v3-turbo",
    "started_at": "2026-05-06T10:15:20+00:00",
    "completed_at": "2026-05-06T10:17:40+00:00",
    "elapsed_seconds": 140.2
  },
  "output_path": "data/mcp-20260506-101520/transcript.json"
}
```

Agent 常见用法：
- 直接读 `transcript.full_text` 做摘要 / 回答用户的问题。
- 遍历 `transcript.paragraphs` 做“按分钟总结 + 带时间戳”的笔记。
- 用 `transcript.segments` + `source.url` 生成可跳转的引用（YouTube 支持 `?t=秒` 跳转）。

## 性能参考

29 分钟中文播客（小宇宙），实测 Groq whisper-large-v3-turbo：

| 阶段 | 耗时 |
|------|------|
| 解析 + 下载 + 转 WAV | ~30s |
| 并行转写（3 块并行） | ~90s |
| **总耗时**（URL → 结构化 JSON） | **~2 分钟** |

## 支持的 URL 示例

- Apple Podcasts: `https://podcasts.apple.com/cn/podcast/xxx/id1234567890?i=1000611111`
- 小宇宙 FM: `https://www.xiaoyuzhoufm.com/episode/69f231defbed7ba941222e98`
- YouTube: `https://www.youtube.com/watch?v=...` / `https://youtu.be/...`
- RSS Feed: `https://feeds.example.com/podcast.xml`
- 直链音频: `https://cdn.example.com/episode-42.mp3`

## 直接 CLI 测试（不走 MCP）

```bash
cp .env.example .env
# 编辑 .env，填入 PKA_GROQ_API_KEY
python test_pipeline.py "https://www.xiaoyuzhoufm.com/episode/xxx"
```

输出：
- `data/test-run/result.json` — 结构化转录（agent-ready）
- `data/test-run/transcript_readable.txt` — 按分钟分段的可读转录

## 可选：一条龙（转写 + LLM 摘要）

如果你想让本工具自己生成摘要 + Agent 记忆块（不通过调用方 Agent），在 `.env` 里额外配置任意 OpenAI 兼容端点：

```bash
PKA_LLM_API_KEY=sk-or-v1-...
PKA_LLM_BASE_URL=https://openrouter.ai/api/v1   # 或 OpenAI / DeepSeek / Moonshot / 本地 vLLM
PKA_LLM_MODEL=meta-llama/llama-4-maverick
```

配置完成后 MCP 会自动多出一个 `extract_knowledge` 工具，输出包含 `summary` 和 `agent_memory` 的完整 JSON。

## REST API 模式（可选）

适合把本工具作为后台服务暴露 HTTP 接口：

```bash
docker run -d -p 6379:6379 redis
uvicorn src.main:app --reload                    # API
celery -A src.celery_app worker --loglevel=info  # Worker
```

端点：
- `POST /api/v1/podcast/process` — 提交任务
- `GET  /api/v1/podcast/jobs/{id}` — 查询进度
- `GET  /api/v1/podcast/jobs/{id}/result` — 获取结果

REST API 模式同样需要 `PKA_LLM_API_KEY`，因为它默认走完整 pipeline。

## 项目结构

```
src/
├── mcp_server.py                    # MCP Server 入口（主推入口）
├── config.py                        # 极简配置（仅 Groq 必填）
├── layers/
│   ├── resolver/
│   │   ├── factory.py               # 平台识别 + 统一 resolve_podcast 入口
│   │   ├── apple.py                 # Apple Podcasts（iTunes Lookup → RSS）
│   │   ├── rss.py                   # 通用 RSS / Atom
│   │   ├── youtube.py               # YouTube
│   │   └── generic.py               # 小宇宙 / 通用（yt-dlp generic）
│   ├── audio/                       # 下载 + 分块
│   ├── transcription/
│   │   ├── factory.py               # Groq 并行转写 + 去重
│   │   └── groq_whisper.py          # Groq Whisper API 客户端
│   ├── semantic/                    # 可选 LLM 摘要
│   ├── memory/                      # 可选 Agent 记忆压缩
│   └── output/                      # 输出组装
├── pipeline/orchestrator.py         # 完整流水线（需 LLM Key）
├── api/                             # 可选 REST API
└── storage/                         # SQLite 持久化
```

## 环境变量速查

| 变量 | 是否必填 | 说明 |
|------|----------|------|
| `PKA_GROQ_API_KEY` | **必填** | Groq Whisper API Key |
| `PKA_GROQ_MODEL` | 选填 | 默认 `whisper-large-v3-turbo` |
| `PKA_LLM_API_KEY` | 选填 | 仅在需要内置摘要时使用 |
| `PKA_LLM_BASE_URL` | 选填 | 兼容 OpenAI 格式的任意端点 |
| `PKA_LLM_MODEL` | 选填 | 默认 `meta-llama/llama-4-maverick` |
| `PKA_DATA_DIR` | 选填 | 输出目录，默认 `./data` |
| `PKA_REDIS_URL` / `PKA_DATABASE_URL` | 选填 | 仅 REST API 模式需要 |

## License

MIT
