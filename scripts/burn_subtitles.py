#!/usr/bin/env python3
"""Burn SRT subtitles into a video using ffmpeg.

Usage:
  python burn_subtitles.py <video.mp4> <subtitles.srt> [output.mp4] [options]

Options:
  --font-size N       subtitle font size (default: 24, bilingual: 18)
  --font NAME         font name (default: Arial)
  --position POS      bottom | top | center  (default: bottom)
  --margin-v N        vertical margin in pixels (default: 30)
  --bilingual         optimise styling for bilingual SRT (smaller font)

Produces output.mp4 with burned-in subtitles.
If output path is omitted, writes <video_name>_subtitled.mp4.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _check_ffmpeg() -> str:
    p = shutil.which('ffmpeg')
    if not p:
        print("ERROR: ffmpeg not found in PATH.", file=sys.stderr)
        print("  Download from https://ffmpeg.org/download.html", file=sys.stderr)
        sys.exit(1)
    return p


def _escape_srt_path(path: str) -> str:
    """Escape a file path for ffmpeg's subtitles filter.

    ffmpeg subtitle filter requires:
    - Forward slashes (even on Windows)
    - Escaped backslashes and colons
    - The path wrapped in the filter argument
    """
    # Convert to absolute path with forward slashes
    p = Path(path).resolve()
    s = str(p).replace('\\', '/')

    # Escape characters that ffmpeg filter parser treats specially
    # On Windows, drive letter colon needs escaping: C:/ → C\:/
    # Also escape backslashes and single quotes
    s = s.replace(':', '\\:')
    s = s.replace("'", "\\'")
    return s


def _build_style(
    font_size: int,
    font_name: str,
    position: str,
    margin_v: int,
    bilingual: bool,
) -> str:
    """Build the force_style string for ffmpeg's subtitles filter."""
    alignment_map = {
        'bottom': 2,    # bottom-center
        'top': 8,       # top-center
        'center': 5,    # middle-center
    }
    alignment = alignment_map.get(position, 2)

    parts = [
        f"FontSize={font_size}",
        f"FontName={font_name}",
        "PrimaryColour=&H00FFFFFF",      # white
        "OutlineColour=&H00000000",      # black outline
        "BackColour=&H80000000",         # semi-transparent black background
        "BorderStyle=3",                  # opaque box (more readable)
        "Outline=1",
        "Shadow=0",
        f"Alignment={alignment}",
        f"MarginV={margin_v}",
        "Bold=0",
    ]

    if bilingual:
        # smaller font, tighter line spacing for bilingual
        parts[0] = f"FontSize={font_size}"
        parts.append("LineSpacing=-2")

    return ','.join(parts)


def burn_subtitles(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    font_size: int = 24,
    font_name: str = 'Arial',
    position: str = 'bottom',
    margin_v: int = 30,
    bilingual: bool = False,
) -> Path:
    """Burn subtitles into video. Returns output path."""
    ffmpeg = _check_ffmpeg()

    # Adjust font size for bilingual if not explicitly set
    if bilingual and font_size == 24:
        font_size = 18

    escaped_srt = _escape_srt_path(str(srt_path))
    style = _build_style(font_size, font_name, position, margin_v, bilingual)

    # Build the filter string
    vf = f"subtitles='{escaped_srt}':force_style='{style}'"

    cmd = [
        ffmpeg, '-y',
        '-i', str(video_path),
        '-vf', vf,
        '-c:v', 'libx264',
        '-crf', '23',
        '-preset', 'medium',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        str(output_path),
    ]

    print(f"Burning subtitles into video...", file=sys.stderr)
    print(f"  Video:   {video_path.name}", file=sys.stderr)
    print(f"  SRT:     {srt_path.name}", file=sys.stderr)
    print(f"  Output:  {output_path.name}", file=sys.stderr)
    print(f"  Style:   {style}", file=sys.stderr)

    # Run without capture_output so user sees progress
    r = subprocess.run(cmd, text=True)

    if r.returncode != 0:
        print(f"\nERROR: ffmpeg failed (exit {r.returncode})", file=sys.stderr)
        sys.exit(1)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"\n✓ Done! Output: {output_path}  ({size_mb:.1f} MB)", file=sys.stderr)
    return output_path


def main():
    ap = argparse.ArgumentParser(
        description='Burn SRT subtitles into a video using ffmpeg',
    )
    ap.add_argument('video', help='Input video file')
    ap.add_argument('srt', help='SRT subtitle file')
    ap.add_argument('output', nargs='?', default=None,
                    help='Output video path (default: <name>_subtitled.mp4)')
    ap.add_argument('--font-size', type=int, default=24,
                    help='Subtitle font size (default: 24)')
    ap.add_argument('--font', default='Arial',
                    help='Font name (default: Arial)')
    ap.add_argument('--position', default='bottom',
                    choices=['bottom', 'top', 'center'],
                    help='Subtitle position (default: bottom)')
    ap.add_argument('--margin-v', type=int, default=30,
                    help='Vertical margin in pixels (default: 30)')
    ap.add_argument('--bilingual', action='store_true',
                    help='Optimise styling for bilingual SRT')
    args = ap.parse_args()

    video_path = Path(args.video).resolve()
    srt_path = Path(args.srt).resolve()

    if not video_path.exists():
        print(f"ERROR: Video not found: {video_path}", file=sys.stderr)
        sys.exit(1)
    if not srt_path.exists():
        print(f"ERROR: SRT not found: {srt_path}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        stem = video_path.stem
        suffix = '_bilingual' if args.bilingual else '_subtitled'
        output_path = video_path.parent / f"{stem}{suffix}.mp4"

    burn_subtitles(
        video_path=video_path,
        srt_path=srt_path,
        output_path=output_path,
        font_size=args.font_size,
        font_name=args.font,
        position=args.position,
        margin_v=args.margin_v,
        bilingual=args.bilingual,
    )


if __name__ == '__main__':
    main()
