# YouTube Translate Skill

粘贴 YouTube 链接 → 自动下载、转写、翻译、烧录字幕 → 输出带双语字幕的 MP4。

## 流水线

```
YouTube URL → yt-dlp 下载 → ffmpeg 提取音频 → faster-whisper 转写 → AI 翻译 → ffmpeg 烧录字幕
```

| 步骤 | 工具 | 产物 |
|------|------|------|
| 1. 下载视频 | yt-dlp | video.mp4 |
| 2. 提取音频 | ffmpeg | audio.wav |
| 3. 语音转写 | faster-whisper | en.srt |
| 4. AI 翻译 | Agent 自身 | zh.srt + bilingual.srt |
| 5. 烧录字幕 | ffmpeg | video_subtitled.mp4 |

## 依赖安装

```bash
pip install yt-dlp faster-whisper
# ffmpeg: winget install ffmpeg / brew install ffmpeg / apt install ffmpeg
```

验证依赖：

```bash
python scripts/check_deps.py
```

## 在 WorkBuddy 上安装

1. 将 `youtube-translate` 目录放到 `~/.workbuddy/skills/`
2. 重启 WorkBuddy 或刷新 skills
3. 对话中粘贴 YouTube 链接即可触发

## 在 Codex / 其他 Agent 上安装

### 方式 A：作为指令文件

将 `SKILL.md` 内容追加到 Agent 的指令文件中：

- **Codex CLI**: 追加到 `AGENTS.md` 或 `~/.codex/instructions.md`
- **Cursor**: 追加到 `.cursorrules`
- **Claude Code**: 追加到 `CLAUDE.md`
- **通用**: 追加到 `.github/copilot-instructions.md` 或项目 README

### 方式 B：作为技能目录

如果 Agent 支持技能目录（如 WorkBuddy），将整个目录放到对应位置，确保 Agent 能发现 `SKILL.md`。

### 脚本调用

无论哪个 Agent，脚本调用方式相同。将 `$SKILL_PATH` 替换为脚本实际路径：

```bash
# Step 1-3：下载 + 提取音频 + 转写
python scripts/download_and_transcribe.py "https://youtube.com/watch?v=xxx" ./output --model base

# Step 4：Agent 自行翻译 en.srt → zh.srt + bilingual.srt
# （读取 en.srt，翻译，写出 zh.srt 和 bilingual.srt）
# 或用工具合并双语：
python scripts/srt_utils.py bilingual ./output/en.srt ./output/zh.srt ./output/bilingual.srt

# Step 5：烧录字幕
python scripts/burn_subtitles.py ./output/video.mp4 ./output/bilingual.srt --bilingual
```

## 脚本说明

| 脚本 | 用途 |
|------|------|
| `scripts/download_and_transcribe.py` | 下载视频 + 提取音频 + faster-whisper 转写为 SRT |
| `scripts/burn_subtitles.py` | 将 SRT 字幕烧录到视频（支持双语样式） |
| `scripts/srt_utils.py` | SRT 解析 / 写入 / 双语合并 |
| `scripts/check_deps.py` | 依赖检查与自动安装 |

## 参数速查

### download_and_transcribe.py

```
python download_and_transcribe.py <url> [output_dir] [options]

  --model SIZE       tiny|base|small|medium|large-v3  (default: base)
  --language LANG    en|zh|ja|ko|fr|de|...|auto  (default: en)
  --device DEVICE    cpu|cuda|auto  (default: auto)
  --quality QUALITY  best|720p|480p  (default: best)
```

### burn_subtitles.py

```
python burn_subtitles.py <video.mp4> <subtitles.srt> [output.mp4] [options]

  --font-size N      字体大小 (default: 24, 双语模式自动调小)
  --font NAME        字体 (default: Arial)
  --position POS     bottom|top|center  (default: bottom)
  --margin-v N       垂直边距像素 (default: 30)
  --bilingual        双语字幕优化样式
```

## 模型选择建议

| 模型 | 大小 | CPU 速度 | GPU 速度 | 精度 | 适用场景 |
|------|------|---------|---------|------|---------|
| tiny | ~75MB | 很快 | 极快 | 一般 | 快速预览 |
| base | ~150MB | 快 | 很快 | 良好 | 日常使用（推荐） |
| small | ~500MB | 中 | 快 | 好 | 追求质量 |
| medium | ~1.5GB | 慢 | 中 | 很好 | 高质量需求 |
| large-v3 | ~3GB | 很慢 | 中 | 最佳 | 最高质量 |
