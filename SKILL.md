---
name: youtube-translate
description: "YouTube 视频翻译流水线 — 粘贴 YouTube 链接，自动完成下载视频、提取音频、faster-whisper 转写英文 SRT、AI 翻译中文字幕、ffmpeg 烧录字幕到视频，一步到位输出带双语字幕的 MP4。当用户需要翻译 YouTube 视频、给 YouTube 视频加中文字幕、YouTube 视频转写翻译、下载并翻译油管视频时使用。触发词：YouTube翻译、YouTube字幕翻译、油管视频翻译、YouTube双语字幕、YouTube中文字幕、translate youtube video、youtube subtitle translate。"
display_name: YouTube 视频翻译
display_name_en: YouTube Video Translate
category: media
version: 1.0.0
author: agent_created
agent_created: true
---

# YouTube 视频翻译流水线

粘贴一个 YouTube 链接，自动完成五步流水线，输出带双语字幕的 MP4 视频。

## 流水线概览

```
YouTube URL
  │
  ▼
[1] yt-dlp 下载  ──→  video.mp4
  │
  ▼
[2] ffmpeg 提取音频  ──→  audio.wav
  │
  ▼
[3] faster-whisper 转写  ──→  en.srt
  │
  ▼
[4] AI 翻译（Agent 执行）  ──→  zh.srt + bilingual.srt
  │
  ▼
[5] ffmpeg 烧录字幕  ──→  video_subtitled.mp4
```

## 依赖

| 工具 | 用途 | 安装 |
|------|------|------|
| yt-dlp | 下载 YouTube 视频 | `pip install yt-dlp` |
| ffmpeg | 音频提取 + 字幕烧录 | `winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg` |
| faster-whisper | 语音转写 | `pip install faster-whisper` |

首次使用前运行依赖检查：

```bash
python "$SKILL_PATH/scripts/check_deps.py"
# 自动安装缺失依赖：
python "$SKILL_PATH/scripts/check_deps.py" --install
```

> **注意：** faster-whisper 首次运行时会自动下载 Whisper 模型（base 模型约 150MB），需要网络连接。

## 执行流程

当用户提供 YouTube 链接时，按以下步骤执行。假设输出目录为 `./output/<video_id>`（可自定义）。

### Step 1-3：下载 + 提取音频 + 转写（一条命令）

```bash
python "$SKILL_PATH/scripts/download_and_transcribe.py" "<youtube_url>" ./output \
  --model base --language en --quality best
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--model` | base | Whisper 模型：tiny / base / small / medium / large-v3。越大越准但越慢 |
| `--language` | en | 源语言代码。视频非英语时改为对应语言（zh/ja/ko/fr/de 等），或 `auto` 自动检测 |
| `--quality` | best | 视频质量：best / 720p / 480p |
| `--device` | auto | cpu / cuda / auto。有 NVIDIA GPU 时用 cuda 大幅加速 |

脚本执行完成后，stdout 输出 JSON 摘要：

```json
{
  "status": "ok",
  "title": "Video Title",
  "detected_language": "en",
  "files": {
    "video": "./output/video.mp4",
    "audio": "./output/audio.wav",
    "srt_en": "./output/en.srt"
  }
}
```

### Step 4：AI 翻译（Agent 执行）

**此步骤由 Agent 自身完成，不调用外部翻译 API。**

1. 读取 `en.srt` 文件内容
2. 参考 `references/translation_guide.md` 中的翻译规范
3. 通读全部字幕，理解上下文
4. 逐条翻译为中文，生成 `zh.srt`（时间轴不变，仅替换文本）
5. 生成 `bilingual.srt`（英文在上，中文在下，同一时间轴）

**翻译要点：**
- 口语化，简洁自然，每行不超过 15-20 字
- 术语全文一致
- 保留语气和情感
- 保留 `[Music]`、`[Applause]` 等声音描述
- 参考详细规范：`references/translation_guide.md`

**生成方式（二选一）：**

方式 A — 直接用 Edit/Write 工具写出两个文件：

```
zh.srt         ← 中文翻译
bilingual.srt  ← 英文+中文双语
```

方式 B — 先写 zh.srt，再用脚本合并双语：

```bash
python "$SKILL_PATH/scripts/srt_utils.py" bilingual ./output/en.srt ./output/zh.srt ./output/bilingual.srt
```

### Step 5：烧录字幕

使用双语字幕烧录（推荐）：

```bash
python "$SKILL_PATH/scripts/burn_subtitles.py" ./output/video.mp4 ./output/bilingual.srt --bilingual
```

或仅烧录中文字幕：

```bash
python "$SKILL_PATH/scripts/burn_subtitles.py" ./output/video.mp4 ./output/zh.srt
```

**可选参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--font-size` | 24（普通）/ 18（双语） | 字体大小 |
| `--font` | Arial | 字体名称 |
| `--position` | bottom | bottom / top / center |
| `--margin-v` | 30 | 垂直边距（像素） |

输出文件：`video_subtitled.mp4`（双语）或 `video_bilingual.mp4`

## 输出文件清单

执行完成后，输出目录包含：

```
output/
├── video.mp4              # 原始下载视频
├── audio.wav              # 提取的音频
├── en.srt                 # 英文字幕
├── zh.srt                 # 中文字幕（Agent 翻译）
├── bilingual.srt          # 双语字幕
└── video_subtitled.mp4    # 最终视频（带字幕）
```

## 脚本说明

| 脚本 | 用途 |
|------|------|
| `scripts/download_and_transcribe.py` | Step 1-3：下载视频 + 提取音频 + 转写 SRT |
| `scripts/burn_subtitles.py` | Step 5：烧录字幕到视频 |
| `scripts/srt_utils.py` | SRT 解析 / 写入 / 双语合并工具 |
| `scripts/check_deps.py` | 依赖检查与安装 |

## 注意事项

- **模型选择：** CPU 上推荐 `base` 或 `small`；有 GPU 可用 `medium` 或 `large-v3` 获得更好效果
- **视频时长：** 超过 30 分钟的视频转写可能较慢，建议用 GPU 或选择 `small` 模型
- **非英语视频：** 将 `--language` 改为源语言代码，或用 `auto` 自动检测。翻译目标语言仍为中文
- **Windows 路径：** 脚本已处理 Windows 路径转义，ffmpeg 字幕烧录在 Windows 上可正常工作
- **网络要求：** 下载视频和首次加载模型需要网络连接
