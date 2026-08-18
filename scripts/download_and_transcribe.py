#!/usr/bin/env python3
"""Download a YouTube video, extract audio, and transcribe with faster-whisper.

Pipeline:
  1. yt-dlp   → download best MP4 (H.264 video + m4a audio merged)
  2. ffmpeg   → extract 16 kHz mono WAV
  3. faster-whisper → transcribe → English SRT

Key features:
  - Auto-detects system proxy on Windows (registry Internet Settings)
  - Ensures deno is on PATH for YouTube PO Token generation (avoids HTTP 403)
  - Prefers H.264 (avc1) formats over AV1 (av01) for better CDN compatibility
  - Passes proxy to Python/HuggingFace for Whisper model download
  - Cleans up stale .part files before downloading

Usage:
  python download_and_transcribe.py <youtube_url> [output_dir] [options]

Options:
  --model SIZE         whisper model: tiny|base|small|medium|large-v3  (default: base)
  --language LANG      source language code, e.g. en, zh, ja  (default: en)
  --device DEVICE      cpu | cuda | auto  (default: auto)
  --quality QUALITY    video quality: best|1080p|720p|480p  (default: best)
  --proxy URL          HTTP/SOCKS proxy (auto-detected if omitted)
  --deno-path PATH     path to deno executable (auto-detected if omitted)

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

# Fix Windows console encoding so ✓/✗/⚠/→/— don't crash on GBK terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ── proxy & environment helpers ────────────────────────────────────

def detect_system_proxy() -> str | None:
    """Detect system proxy (Windows registry, then env vars)."""
    # 1. Windows registry
    if sys.platform == 'win32':
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
            )
            enable, _ = winreg.QueryValueEx(key, 'ProxyEnable')
            if enable:
                server, _ = winreg.QueryValueEx(key, 'ProxyServer')
                winreg.CloseKey(key)
                # Normalise: registry value may be "http=host:port;https=host:port" or just "host:port"
                if '=' in server:
                    for part in server.split(';'):
                        if part.startswith('https=') or part.startswith('http='):
                            server = part.split('=', 1)[1]
                            break
                if not server.startswith('http'):
                    server = f'http://{server}'
                return server
            winreg.CloseKey(key)
        except Exception:
            pass

    # 2. Environment variables
    for var in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'):
        val = os.environ.get(var)
        if val:
            return val

    return None


def ensure_deno_on_path(deno_path: str | None = None) -> str | None:
    """Ensure deno is available on PATH. Returns deno version or None.

    If deno_path points to a directory, that directory is added to PATH.
    If it points to a file, its parent directory is added.
    """
    if deno_path:
        p = Path(deno_path).expanduser().resolve()
        if p.is_dir():
            deno_dir = str(p)
            # Check for deno binary in this directory (account for .exe on Windows)
            exe_name = 'deno.exe' if sys.platform == 'win32' else 'deno'
            if not (p / exe_name).exists() and not (p / 'deno').exists():
                print(f"  WARNING: deno binary not found in directory: {p}", file=sys.stderr)
        elif p.is_file():
            deno_dir = str(p.parent)
        else:
            # Path doesn't exist; use parent as directory and warn
            deno_dir = str(p.parent)
            print(f"  WARNING: --deno-path does not exist: {p}", file=sys.stderr)

        # Add to PATH using proper path-segment comparison (not substring match)
        path_dirs = os.environ.get('PATH', '').split(os.pathsep)
        if deno_dir not in path_dirs:
            os.environ['PATH'] = deno_dir + os.pathsep + os.environ.get('PATH', '')

    if shutil.which('deno'):
        try:
            r = subprocess.run(['deno', '--version'], capture_output=True, text=True, timeout=10)
            return r.stdout.split('\n')[0] if r.stdout else 'found'
        except Exception:
            return 'found'
    return None


def set_proxy_env(proxy: str | None):
    """Set proxy environment variables for Python (HuggingFace downloads)."""
    if proxy:
        os.environ['HTTPS_PROXY'] = proxy
        os.environ['HTTP_PROXY'] = proxy
        os.environ['https_proxy'] = proxy
        os.environ['http_proxy'] = proxy


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
            print(f"    Or download nightly: https://github.com/yt-dlp/yt-dlp-nightly-builds/releases", file=sys.stderr)
        elif name == 'ffmpeg':
            print(f"    https://ffmpeg.org/download.html", file=sys.stderr)
        elif name == 'deno':
            print(f"    winget install DenoLand.Deno", file=sys.stderr)
            print(f"    Or download from https://github.com/denoland/deno/releases", file=sys.stderr)
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

# Format selectors that prefer H.264 (avc1) over AV1 (av01).
# AV1 streams are more likely to be throttled/403'd by YouTube CDNs.
# Audio: prefer MP4 (mp4a) audio tracks for best compatibility.
# Note: we do NOT select a specific language track; yt-dlp picks the
# default/best audio track. Final /best fallback ensures we can still
# download even if no avc1/mp4a format is available (may fall back to AV1).
_QUALITY_FORMATS = {
    'best':   'bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[vcodec^=avc1]/best[ext=mp4]/best',
    '1080p':  'bestvideo[height<=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[height<=1080][vcodec^=avc1]/best[height<=1080][ext=mp4]/best[height<=1080]',
    '720p':   'bestvideo[height<=720][vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[height<=720][vcodec^=avc1]/best[height<=720][ext=mp4]/best[height<=720]',
    '480p':   'bestvideo[height<=480][vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[height<=480][vcodec^=avc1]/best[height<=480][ext=mp4]/best[height<=480]',
}


def download_video(
    url: str,
    out_dir: Path,
    quality: str = 'best',
    proxy: str | None = None,
) -> tuple[Path, str, str]:
    """Download video with yt-dlp. Returns (video_path, title, duration_str)."""
    ytdlp = _check_tool('yt-dlp')

    fmt = _QUALITY_FORMATS.get(quality, _QUALITY_FORMATS['best'])
    out_template = str(out_dir / 'video.%(ext)s')

    # Clean up stale .part files from previous failed attempts
    for part in out_dir.glob('*.part'):
        print(f"  Cleaning stale file: {part.name}", file=sys.stderr)
        part.unlink(missing_ok=True)

    cmd = [
        ytdlp,
        '--no-playlist',
        '--no-warnings',
        '--merge-output-format', 'mp4',
        '-f', fmt,
        '-o', out_template,
        '--retries', '10',
        '--fragment-retries', '10',
        '--socket-timeout', '30',
        '--print', '%(title)s',
        '--print', '%(duration)s',
    ]
    if proxy:
        cmd += ['--proxy', proxy]
    cmd.append(url)

    print("\n[1/3] Downloading video...", file=sys.stderr)
    if proxy:
        print(f"  Using proxy: {proxy}", file=sys.stderr)
    r = _run(cmd)

    lines = r.stdout.strip().split('\n')

    video_path = out_dir / 'video.mp4'
    if not video_path.exists():
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
        '-nostats',               # suppress progress stats (avoids log spam)
        '-loglevel', 'error',     # only show errors
        str(audio_path),
    ]
    _run(cmd)

    print(f"  ✓ Audio: {audio_path.name}  ({audio_path.stat().st_size // 1024} KB)", file=sys.stderr)
    return audio_path


# ── step 3: transcribe ─────────────────────────────────────────────

def _is_cuda_init_error(exc: Exception) -> bool:
    """Heuristic: does this exception look like a CUDA initialization /
    runtime-library error (safe to fall back to CPU), rather than a
    wrong model name, download failure, or permission error (which should
    be surfaced to the user)?"""
    msg = str(exc).lower()
    keywords = [
        'cuda', 'cudnn', 'cublas', 'cufft', 'curand', 'cusolver', 'cusparse',
        'nvidia', 'gpu', 'could not load library', 'no kernel image',
        'device-side assert', 'not compiled with cuda', 'no cuda-capable',
        'cuda-capable device', 'driver version', 'nvrtc',
    ]
    return any(kw in msg for kw in keywords)


def transcribe(
    audio_path: Path,
    out_dir: Path,
    model_size: str = 'base',
    language: str = 'en',
    device: str = 'auto',
) -> tuple[Path, str]:
    """Transcribe audio with faster-whisper, output SRT."""
    _check_python_pkg('faster_whisper', 'faster-whisper')
    from faster_whisper import WhisperModel

    srt_path = out_dir / 'en.srt'

    print(f"\n[3/3] Transcribing (model={model_size}, lang={language}, device={device})...", file=sys.stderr)
    print(f"  (first run downloads the model — this may take a moment)", file=sys.stderr)

    # If auto, try CUDA first and fall back to CPU only for CUDA init errors
    if device == 'auto':
        try:
            compute_type = 'default'
            model = WhisperModel(model_size, device='cuda', compute_type=compute_type)
            device = 'cuda'
            print(f"  Using CUDA GPU", file=sys.stderr)
        except Exception as e:
            if _is_cuda_init_error(e):
                print(f"  CUDA unavailable ({e}), falling back to CPU", file=sys.stderr)
                device = 'cpu'
                compute_type = 'int8'
                model = WhisperModel(model_size, device='cpu', compute_type=compute_type)
            else:
                # Not a CUDA init error (wrong model name, download failure, etc.)
                print(f"  Failed to load model: {e}", file=sys.stderr)
                raise
    else:
        compute_type = 'int8' if device == 'cpu' else 'default'
        model = WhisperModel(model_size, device=device, compute_type=compute_type)

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
            if i % 100 == 0:
                print(f"  ...{i} segments transcribed", file=sys.stderr)

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
                    choices=['best', '1080p', '720p', '480p'],
                    help='best | 1080p | 720p | 480p (default: best)')
    ap.add_argument('--proxy', default=None,
                    help='HTTP/SOCKS proxy URL (auto-detected from system if omitted)')
    ap.add_argument('--deno-path', default=None,
                    help='Path to deno executable directory or binary (auto-detected if omitted)')
    args = ap.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # add script dir to path for srt_utils import
    script_dir = Path(__file__).parent.resolve()
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    # ── Environment setup ──
    # 1. Proxy: CLI arg > system detection
    proxy = args.proxy or detect_system_proxy()
    if proxy:
        print(f"  Proxy: {proxy}", file=sys.stderr)
        set_proxy_env(proxy)

    # 2. Deno: required by yt-dlp for YouTube PO Token (avoids HTTP 403)
    deno_ver = ensure_deno_on_path(args.deno_path)
    if deno_ver:
        print(f"  Deno: {deno_ver}", file=sys.stderr)
    else:
        print("  WARNING: deno not found. YouTube downloads may fail with HTTP 403.", file=sys.stderr)
        print("  Install deno: winget install DenoLand.Deno", file=sys.stderr)

    # Step 1: download
    video_path, title, duration_str = download_video(args.url, out_dir, args.quality, proxy)

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
