#!/usr/bin/env python3
"""Download a YouTube video, extract audio, and transcribe with faster-whisper.

Pipeline:
  1. yt-dlp   → download best MP4 (video + audio merged)
  2. ffmpeg   → extract 16 kHz mono WAV
  3. faster-whisper → transcribe → English SRT

Usage:
  python download_and_transcribe.py <youtube_url> [output_dir] [options]

Options:
  --model SIZE         whisper model: tiny|base|small|medium|large-v3  (default: base)
  --language LANG      source language code, e.g. en, zh, ja  (default: en)
  --device DEVICE      cpu | cuda | auto  (default: auto)
  --quality QUALITY    video quality: best|720p|480p  (default: best)

Output files (in output_dir):
  video.mp4     — downloaded video
  audio.wav     — extracted audio
  en.srt        — English (source language) subtitles
  metadata.json — { url, title, duration, language, model, files }

The script prints a JSON summary at the end so the agent can parse it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# ── helpers ────────────────────────────────────────────────────────

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run a command, raise on failure."""
    print(f"  $ {' '.join(str(c) for c in cmd)}", file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(f"  STDOUT: {r.stdout[:2000]}", file=sys.stderr)
        print(f"  STDERR: {r.stderr[:2000]}", file=sys.stderr)
        raise RuntimeError(f"Command failed (exit {r.returncode}): {cmd[0]}")
    return r


def _check_tool(name: str) -> str:
    """Return the path to a CLI tool, or exit with a helpful message."""
    path = shutil.which(name)
    if not path:
        print(f"ERROR: '{name}' not found in PATH.", file=sys.stderr)
        print(f"  Install it and retry:", file=sys.stderr)
        if name == 'yt-dlp':
            print(f"    pip install yt-dlp", file=sys.stderr)
        elif name == 'ffmpeg':
            print(f"    https://ffmpeg.org/download.html", file=sys.stderr)
        sys.exit(1)
    return path


def _check_python_pkg(pkg: str, pip_name: str | None = None):
    """Check if a Python package is importable; exit with hint if not."""
    try:
        __import__(pkg)
    except ImportError:
        pip_name = pip_name or pkg
        print(f"ERROR: Python package '{pkg}' not found.", file=sys.stderr)
        print(f"  Install it:  pip install {pip_name}", file=sys.stderr)
        sys.exit(1)


# ── step 1: download ───────────────────────────────────────────────

def download_video(
    url: str,
    out_dir: Path,
    quality: str = 'best',
) -> tuple[Path, str]:
    """Download video with yt-dlp. Returns (video_path, title)."""
    ytdlp = _check_tool('yt-dlp')

    # quality → format selector
    fmt_map = {
        'best':  'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '720p':  'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
        '480p':  'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]',
    }
    fmt = fmt_map.get(quality, fmt_map['best'])

    out_template = str(out_dir / 'video.%(ext)s')

    cmd = [
        ytdlp,
        '--no-playlist',
        '--no-warnings',
        '--merge-output-format', 'mp4',
        '-f', fmt,
        '-o', out_template,
        '--print', '%(title)s',
        '--print', '%(duration)s',
        url,
    ]

    print("\n[1/3] Downloading video...", file=sys.stderr)
    r = _run(cmd)

    # yt-dlp prints metadata to stdout (one per --print line)
    # but the file might already exist, so check
    lines = r.stdout.strip().split('\n')

    video_path = out_dir / 'video.mp4'
    if not video_path.exists():
        # try to find any mp4
        mp4s = list(out_dir.glob('video.*'))
        if mp4s:
            video_path = mp4s[0]
        else:
            raise RuntimeError("Video file not found after download")

    title = lines[0] if lines else 'Unknown'
    duration_str = lines[1] if len(lines) > 1 else '0'

    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"  ✓ Video: {video_path.name}  ({size_mb:.1f} MB)", file=sys.stderr)
    print(f"  ✓ Title: {title}", file=sys.stderr)

    return video_path, title, duration_str


# ── step 2: extract audio ──────────────────────────────────────────

def extract_audio(video_path: Path, out_dir: Path) -> Path:
    """Extract 16 kHz mono WAV from video using ffmpeg."""
    ffmpeg = _check_tool('ffmpeg')
    audio_path = out_dir / 'audio.wav'

    print("\n[2/3] Extracting audio...", file=sys.stderr)
    cmd = [
        ffmpeg, '-y',
        '-i', str(video_path),
        '-vn',                    # no video
        '-acodec', 'pcm_s16le',   # 16-bit PCM
        '-ar', '16000',           # 16 kHz (whisper requirement)
        '-ac', '1',               # mono
        str(audio_path),
    ]
    _run(cmd)

    print(f"  ✓ Audio: {audio_path.name}  ({audio_path.stat().st_size // 1024} KB)", file=sys.stderr)
    return audio_path


# ── step 3: transcribe ─────────────────────────────────────────────

def transcribe(
    audio_path: Path,
    out_dir: Path,
    model_size: str = 'base',
    language: str = 'en',
    device: str = 'auto',
) -> Path:
    """Transcribe audio with faster-whisper, output SRT."""
    _check_python_pkg('faster_whisper', 'faster-whisper')
    from faster_whisper import WhisperModel

    srt_path = out_dir / 'en.srt'

    print(f"\n[3/3] Transcribing (model={model_size}, lang={language}, device={device})...", file=sys.stderr)
    print(f"  (first run downloads the model — this may take a moment)", file=sys.stderr)

    compute_type = 'int8' if device == 'cpu' else 'default'

    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
    )

    segments_gen, info = model.transcribe(
        str(audio_path),
        language=language if language != 'auto' else None,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
    )

    print(f"  Detected language: {info.language} (prob: {info.language_probability:.2f})", file=sys.stderr)
    print(f"  Duration: {info.duration:.1f}s", file=sys.stderr)

    # Build SRT
    import srt_utils
    segments: list[srt_utils.Segment] = []
    for i, seg in enumerate(segments_gen, 1):
        text = seg.text.strip()
        if text:
            segments.append(srt_utils.Segment(
                index=i,
                start=seg.start,
                end=seg.end,
                text=text,
            ))

    srt_utils.write_srt(segments, srt_path)
    print(f"  ✓ SRT: {srt_path.name}  ({len(segments)} segments)", file=sys.stderr)

    return srt_path, info.language


# ── main ───────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='Download YouTube video → extract audio → transcribe to SRT',
    )
    ap.add_argument('url', help='YouTube video URL')
    ap.add_argument('output_dir', nargs='?', default='.',
                    help='Output directory (default: current dir)')
    ap.add_argument('--model', default='base',
                    help='Whisper model size (default: base)')
    ap.add_argument('--language', default='en',
                    help='Source language code (default: en)')
    ap.add_argument('--device', default='auto',
                    help='cpu | cuda | auto (default: auto)')
    ap.add_argument('--quality', default='best',
                    help='best | 720p | 480p (default: best)')
    args = ap.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # add script dir to path for srt_utils import
    script_dir = Path(__file__).parent.resolve()
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    # Step 1: download
    video_path, title, duration_str = download_video(args.url, out_dir, args.quality)

    # Step 2: extract audio
    audio_path = extract_audio(video_path, out_dir)

    # Step 3: transcribe
    srt_path, detected_lang = transcribe(
        audio_path, out_dir,
        model_size=args.model,
        language=args.language,
        device=args.device,
    )

    # Summary JSON (printed to stdout for the agent to parse)
    summary = {
        'status': 'ok',
        'url': args.url,
        'title': title,
        'duration': duration_str,
        'detected_language': detected_lang,
        'model': args.model,
        'files': {
            'video': str(video_path),
            'audio': str(audio_path),
            'srt_en': str(srt_path),
        },
        'output_dir': str(out_dir),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
