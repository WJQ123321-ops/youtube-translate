---
name: youtube-translate
description: "YouTube 视频翻译流水线 — 粘贴 YouTube 链接，自动完成下载视频、提取音频、faster-whisper 转写英文 SRT、AI 翻译中文字幕、ffmpeg 烧录字幕到视频，一步到位输出带双语字幕的 MP4。当用户需要翻译 YouTube 视频、给 YouTube 视频加中文字幕、YouTube 视频转写翻译、下载并翻译油管视频时使用。触发词：YouTube翻译、YouTube字幕翻译、油管视频翻译、YouTube双语字幕、YouTube中文字幕、translate youtube video、youtube subtitle translate。"
display_name: YouTube 视频翻译
display_name_en: YouTube Video Translate
category: media
version: 1.3.0
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
| yt-dlp | 下载 YouTube 视频 | **推荐 nightly 版**：从 [yt-dlp-nightly-builds](https://github.com/yt-dlp/yt-dlp-nightly-builds/releases) 下载独立 exe；或 `pip install yt-dlp`（稳定版可能不支持 PO Token） |
| ffmpeg | 音频提取 + 字幕烧录 | `winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg` |
| faster-whisper | 语音转写 | `pip install faster-whisper` |
| **deno** | **JS 运行时，yt-dlp 生成 YouTube PO Token 必需** | `winget install DenoLand.Deno` 或从 [deno releases](https://github.com/denoland/deno/releases) 下载 |

> **deno 是关键依赖。** YouTube 现在要求 PO Token 反爬验证，没有 deno 会导致所有视频流下载返回 **HTTP 403 Forbidden**。yt-dlp 会自动调用 deno 生成 token，只需确保 deno 在 PATH 中即可。

首次使用前运行依赖检查：

```bash
python "$SKILL_PATH/scripts/check_deps.py"
# 自动安装缺失依赖：
python "$SKILL_PATH/scripts/check_deps.py" --install
```

> **注意：** faster-whisper 首次运行时会自动下载 Whisper 模型（base 模型约 150MB），需要网络连接。脚本会自动将系统代理传递给 Python/HuggingFace。

## 网络与代理

脚本会自动检测代理，按以下优先级：
1. `--proxy` 命令行参数
2. Windows 注册表系统代理（Internet Settings）
3. `HTTPS_PROXY` / `HTTP_PROXY` 环境变量

如果 YouTube 在你的网络环境被封锁，确保代理软件已开启并设置了系统代理，脚本会自动使用。

### HTTP 403 排查清单

如果下载视频时遇到 `HTTP Error 403: Forbidden`：

1. **检查 deno 是否安装**：`deno --version`。没有 deno 就无法生成 PO Token，这是 403 的最常见原因。
2. **更新 yt-dlp 到 nightly**：稳定版可能尚未适配 YouTube 最新的反爬变更。从 [nightly releases](https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest) 下载 `yt-dlp.exe`。
3. **清理残留文件**：删除输出目录中的 `*.part` 文件后重试。
4. **检查代理**：确保代理可用（`curl --proxy <proxy> -I https://www.youtube.com`）。
5. **格式选择**：脚本默认优先 H.264（avc1）格式，AV1（av01）流更容易被 CDN 限速或 403。

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
| `--quality` | best | 视频质量：best / 1080p / 720p / 480p。默认优先 H.264 编码 |
| `--device` | auto | cpu / cuda / auto。auto 仅在 CUDA 初始化/运行库错误时回退 CPU；模型名错误、下载失败等会直接报错 |
| `--proxy` | 自动检测 | HTTP/SOCKS 代理 URL |
| `--deno-path` | 自动检测 | deno 可执行文件**或其所在目录**。传目录时直接加入 PATH，传文件时加入其父目录 |

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

**推荐：双层字幕模式**（英文小字在上、中文大字在下，视觉层次分明）：

```bash
python "$SKILL_PATH/scripts/burn_subtitles.py" ./output/video.mp4 \
  --dual ./output/en.srt ./output/zh.srt
```

或使用双语 SRT（英文+中文在同一条字幕中）：

```bash
python "$SKILL_PATH/scripts/burn_subtitles.py" ./output/video.mp4 ./output/bilingual.srt --bilingual
```

仅烧录中文字幕：

```bash
python "$SKILL_PATH/scripts/burn_subtitles.py" ./output/video.mp4 ./output/zh.srt
```

**字幕样式特性：**
- **中文字体自动检测**：Windows 自动使用微软雅黑（Microsoft YaHei），macOS 使用苹方（PingFang SC），Linux 使用 Noto Sans CJK，无需手动指定 `--font`；检测失败时回退到 Arial
- **分辨率自适应**：通过 ffprobe 检测视频高度，字体大小和边距按 1080p 基准等比缩放（1080p 双语：font-size=20, margin-v=48）；ffprobe 缺失或异常时打印 warning 并回退 1080p
- **双层模式**：英文行 75% 字号、半透明白色；中文行 100% 字号、纯白。支持 `--position top/bottom` 控制整体位置（`center` 回退为 bottom 布局以保证两行不重叠）
- **半透明黑底**：BorderStyle=3 保证字幕在任何画面上都可读
- **路径转义**：自动处理 Windows 路径中的反斜杠、冒号、单引号、逗号、分号等特殊字符

**可选参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dual EN ZH` | 无 | 双层模式：英文 SRT 在上、中文 SRT 在下（推荐）。支持 `--position` 控制整体位置 |
| `--bilingual` | 无 | 双语 SRT 模式（两条文本在同一字幕条目中） |
| `--font-size` | 自动缩放 | 字体大小（省略时按视频分辨率自动计算） |
| `--font` | 自动检测 | 字体名称（省略时自动检测中文字体，失败回退 Arial） |
| `--position` | bottom | bottom / top / center（dual 模式下 center 回退为 bottom 布局） |
| `--margin-v` | 自动缩放 | 垂直边距（像素，省略时自动计算） |
| `--crf` | 23 | x264 质量参数（越小质量越高） |
| `--preset` | medium | x264 编码预设 |

输出文件：`video_dual.mp4`（双层）、`video_bilingual.mp4`（双语）或 `video_subtitled.mp4`（单语）

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
| `scripts/download_and_transcribe.py` | Step 1-3：下载视频 + 提取音频 + 转写 SRT（含代理检测、deno 支持、CUDA 回退） |
| `scripts/burn_subtitles.py` | Step 5：烧录字幕（中文字体自动检测、分辨率自适应、双层字幕模式） |
| `scripts/srt_utils.py` | SRT 解析 / 写入 / 双语合并工具 |
| `scripts/check_deps.py` | 依赖检查与安装（含 deno 检测、yt-dlp 版本检查、代理检测） |

## 注意事项

- **deno 必需**：没有 deno 会导致 YouTube 下载 403。这是最常见的失败原因。
- **yt-dlp 版本**：YouTube 反爬机制频繁变化，建议使用 nightly 版而非稳定版。
- **模型选择：** CPU 上推荐 `base` 或 `small`；有 GPU 可用 `medium` 或 `large-v3` 获得更好效果。`device=auto` 仅在 CUDA 初始化/运行库错误时回退 CPU；模型名错误、下载失败等会直接抛出，不会静默回退。
- **视频时长：** 超过 30 分钟的视频转写可能较慢（CPU base 模型约为实时的 2-3 倍速），建议用 GPU 或选择 `small` 模型。
- **非英语视频：** 将 `--language` 改为源语言代码，或用 `auto` 自动检测。翻译目标语言仍为中文。
- **SRT 编码：** `srt_utils.py` 读取时自动尝试 UTF-8 BOM、UTF-8、UTF-16、UTF-16-LE、UTF-16-BE 及系统默认编码，写出统一使用 UTF-8。
- **Windows 路径：** 脚本已处理 Windows 路径转义（含空格、中文、单引号、逗号、分号），ffmpeg 字幕烧录在 Windows 上可正常工作。
- **网络要求：** 下载视频和首次加载模型需要网络连接。脚本会自动使用系统代理。
- **H.264 优先：** 脚本默认优先选择 H.264（avc1）视频和 MP4（mp4a）音频，AV1（av01）流更容易被 YouTube CDN 限速或 403。最终保留 `/best` 回退以确保下载成功率。
- **依赖检查：** `check_deps.py --install` 安装成功后会重新检查并更新状态，退出码反映最终结果。deno 自动安装仅在 Windows（winget）上支持，其他平台请按提示手动安装。
