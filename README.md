# Podcast Knowledge Agent

将播客/音频 URL 转化为 AI Agent 可直接消费的结构化知识（转录文本、摘要、Agent 记忆块）。

## 功能特性

- **多平台支持**：YouTube、RSS Feed、小宇宙等任意含音频的网页
- **本地语音识别**：基于 faster-whisper（CPU），支持中英文等多语言
- **LLM 智能摘要**：通过 OpenRouter 调用 LLM 生成结构化摘要
- **Agent 记忆压缩**：将长文本压缩为 token 预算内的记忆块，便于 Agent 检索
- **MCP Server**：支持 Claude Desktop / Claude Code 等 AI 工具直接调用
- **REST API**：FastAPI 异步接口，支持 Celery 任务队列

## 架构概览

```
URL → 平台解析 → 音频下载 → 分块 → 语音识别 → LLM摘要 → 记忆压缩 → 结构化JSON
```

### 处理流水线

| 阶段 | 说明 |
|------|------|
| 1. Resolver | 解析 URL，提取元数据（标题、作者、时长） |
| 2. Audio Extractor | 下载音频并转换为 16kHz WAV |
| 3. Chunker | 按 10 分钟切片（30 秒重叠） |
| 4. Transcription | faster-whisper 本地转录（支持 base/small/medium/large-v3） |
| 5. Summarizer | LLM 分块分析 + 合并生成结构化摘要 |
| 6. Memory Compressor | 事实/观点/行动项提取 → 重要性评分 → token 预算裁剪 |
| 7. Output Assembler | 组装最终 JSON，含时间轴段落 |

## 快速开始

### 环境要求

- Python 3.11+
- ffmpeg（系统安装或通过 `pip install imageio-ffmpeg` 自动获取）
- Redis（仅 API 模式需要，直接运行脚本不需要）

### 安装

```bash
git clone https://github.com/ellenfengyunjing/podcast-to-md-tool-for-agent.git
cd podcast-to-md-tool-for-agent

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -e ".[dev]"
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 OpenRouter API Key
```

### 直接运行（推荐测试）

```bash
python test_pipeline.py "https://www.xiaoyuzhoufm.com/episode/xxx"
```

输出文件：
- `data/<job-id>/result.json` — 完整结构化数据
- `data/<job-id>/transcript_readable.txt` — 按分钟分段的可读转录文本

### API 模式

```bash
# 启动 Redis
docker run -d -p 6379:6379 redis

# 启动 API 服务
uvicorn src.main:app --reload

# 启动 Celery Worker
celery -A src.celery_app worker --loglevel=info
```

## MCP Server（Agent 集成）

本项目提供 MCP (Model Context Protocol) Server，可让 Claude Desktop、Claude Code 等 AI 工具直接调用播客知识提取能力。

### 配置 Claude Desktop

在 `claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "podcast-knowledge": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/podcast-to-md-tool-for-agent",
      "env": {
        "PKA_OPENROUTER_API_KEY": "sk-or-v1-your-key"
      }
    }
  }
}
```

### 配置 Claude Code

```bash
claude mcp add podcast-knowledge -- python -m src.mcp_server
```

### MCP 工具列表

| 工具名 | 说明 |
|--------|------|
| `process_podcast` | 输入 URL，返回完整结构化知识 JSON |
| `get_transcript` | 输入 URL，仅返回转录文本 |
| `get_summary` | 输入 URL，仅返回摘要 |

## 输出数据结构

```json
{
  "metadata": {
    "source_url": "https://...",
    "platform": "generic",
    "title": "节目标题",
    "duration_seconds": 1748.7,
    "language": "zh"
  },
  "transcript": {
    "segments": [{"start": 0.0, "end": 5.2, "text": "...", "speaker": "SPEAKER_00"}],
    "paragraphs": [{"time_label": "00:00 - 01:00", "text": "..."}],
    "full_text": "...",
    "word_count": 9401
  },
  "summary": {
    "title": "生成的标题",
    "one_line_summary": "一句话摘要",
    "executive_summary": "详细摘要",
    "key_topics": [{"topic": "...", "summary": "..."}],
    "key_insights": ["..."],
    "entities": [{"name": "...", "type": "person"}]
  },
  "agent_memory": {
    "retrieval_summary": "检索摘要",
    "memory_blocks": [
      {
        "block_type": "fact",
        "content": "...",
        "importance_score": 0.85,
        "tokens": 45,
        "tags": ["AI", "编程"]
      }
    ],
    "total_tokens": 478,
    "compression_ratio": 0.06
  }
}
```

## 项目结构

```
src/
├── main.py                     # FastAPI 应用入口
├── config.py                   # 配置管理 (pydantic-settings)
├── celery_app.py               # Celery 实例
├── mcp_server.py               # MCP Server 入口
├── api/v1/
│   ├── endpoints/podcast.py    # REST API 端点
│   └── schemas/response.py     # Pydantic 数据模型
├── layers/
│   ├── resolver/               # URL 解析（YouTube/RSS/通用）
│   ├── audio/                  # 音频下载 & 分块
│   ├── transcription/          # 语音识别（本地 whisper）
│   ├── semantic/               # LLM 摘要生成
│   ├── memory/                 # Agent 记忆压缩
│   └── output/                 # 输出组装
├── pipeline/orchestrator.py    # 流水线编排
└── storage/                    # 数据库 & 持久化
```

## 技术栈

| 组件 | 选型 |
|------|------|
| Web 框架 | FastAPI (async) |
| 任务队列 | Celery + Redis |
| 语音识别 | faster-whisper (本地) / Groq Whisper API (云端) |
| LLM | OpenRouter (meta-llama/llama-4-maverick) |
| 音频处理 | yt-dlp + ffmpeg |
| 数据验证 | Pydantic v2 |
| 数据库 | SQLite + SQLAlchemy 2.0 async |
| Agent 协议 | MCP (Model Context Protocol) |

## 语音识别方案

本项目支持两种 ASR 方案，用户可通过 `PKA_ASR_BACKEND` 环境变量切换：

| 方案 | 配置值 | 速度 | 成本 | 适用场景 |
|------|--------|------|------|----------|
| **本地 faster-whisper** | `local` | 慢（~1x 实时） | 免费 | 离线使用、隐私敏感 |
| **Groq Whisper API** | `groq` | 极快（~100x 实时） | 免费额度 8h/天 | 推荐日常使用 |
| OpenRouter Audio | `api` | 中等 | 按量付费 | 备选方案 |

### 使用 Groq（推荐，速度最快）

```bash
# .env 中配置
PKA_ASR_BACKEND=groq
PKA_GROQ_API_KEY=gsk_your-key-here  # 在 https://console.groq.com 免费获取
```

30 分钟音频约 10 秒完成转写，自带标点符号和时间戳。

### 使用本地 faster-whisper（离线）

```bash
PKA_ASR_BACKEND=local
PKA_WHISPER_MODEL_SIZE=medium  # base/small/medium/large-v3
```

无需网络，但 CPU 转写较慢（30 分钟音频约 45 分钟处理）。

## 配置说明

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `PKA_OPENROUTER_API_KEY` | OpenRouter API 密钥（LLM 摘要用） | (必填) |
| `PKA_ASR_BACKEND` | 语音识别后端：`local`、`groq`、`api` | `local` |
| `PKA_GROQ_API_KEY` | Groq API 密钥（ASR 用） | (groq 模式必填) |
| `PKA_WHISPER_MODEL_SIZE` | 本地 Whisper 模型大小 | `large-v3` |
| `PKA_LLM_MODEL` | LLM 模型名称 | `meta-llama/llama-4-maverick` |
| `PKA_DATA_DIR` | 数据存储目录 | `./data` |

## 测试

```bash
# 运行单元测试
pytest tests/

# 运行端到端测试
python test_pipeline.py "https://www.xiaoyuzhoufm.com/episode/xxx"
```

## License

MIT
