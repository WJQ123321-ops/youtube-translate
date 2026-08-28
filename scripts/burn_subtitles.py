#!/usr/bin/env python3
"""Burn SRT subtitles into a video using ffmpeg.

Supports three modes:
  1. Single-language:  burn_subtitles.py video.mp4 zh.srt
  2. Bilingual (one SRT, two lines per entry):
                       burn_subtitles.py video.mp4 bilingual.srt --bilingual
  3. Dual-layer (two separate SRTs, English on top / Chinese below):
                       burn_subtitles.py video.mp4 --dual en.srt zh.srt

Features:
  - Auto-detects CJK fonts (Microsoft YaHei / PingFang SC / Noto Sans CJK)
  - Auto-scales font size & margins to video resolution (via ffprobe)
  - Clean outline+shadow look by default (--style box for opaque boxes)
  - Dual-layer: English ~72% size in light grey above the white Chinese line

Usage:
  python burn_subtitles.py <video.mp4> <subtitles.srt> [output.mp4] [options]

Options:
  --font-size N       subtitle font size (auto-scaled if omitted)
  --font NAME         font name (auto-detected for CJK if omitted)
  --position POS      bottom | top | center  (default: bottom)
  --margin-v N        vertical margin in pixels (auto-scaled if omitted)
  --bilingual         optimise styling for bilingual SRT (two-line entries)
  --dual EN ZH        dual-layer: burn English SRT on top, Chinese SRT below
  --crf N             x264 CRF value (default: 23)
  --preset P          x264 preset (default: medium)
  --encoder NAME      auto | libx264 | nvenc  (default: auto — h264_nvenc
                      when an NVIDIA GPU is available, else libx264)

Produces output.mp4 with burned-in subtitles.
If output path is omitted, writes <video_name>_subtitled.mp4.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Fix Windows console encoding so ✓/✗/⚠/→/— don't crash on GBK terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ── tool detection ─────────────────────────────────────────────────

def _check_tool(name: str) -> str:
    p = shutil.which(name)
    if not p:
        print(f"ERROR: {name} not found in PATH.", file=sys.stderr)
        if name == 'ffmpeg':
            print("  Download from https://ffmpeg.org/download.html", file=sys.stderr)
        elif name == 'ffprobe':
            print("  ffprobe usually comes with ffmpeg.", file=sys.stderr)
        sys.exit(1)
    return p


def _nvenc_available(ffmpeg: str) -> bool:
    """Probe whether this ffmpeg build can encode h264_nvenc (NVIDIA GPU).

    Encodes a single 256x256 null frame to /dev/null — fast and side-effect
    free. Fails cleanly when no NVIDIA GPU/driver is present. (256x256, not
    smaller: NVENC rejects frame dimensions below its ~145x49 minimum.)
    """
    try:
        r = subprocess.run(
            [ffmpeg, '-hide_banner', '-v', 'error', '-f', 'lavfi',
             '-i', 'nullsrc=s=256x256:d=0.2', '-frames:v', '1',
             '-c:v', 'h264_nvenc', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


# ── video resolution ───────────────────────────────────────────────

def get_video_height(video_path: Path) -> int:
    """Return video height in pixels using ffprobe.

    Falls back to 1080 with a warning if ffprobe is missing or returns
    invalid data.
    """
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        print("  WARNING: ffprobe not found; assuming 1080p for font scaling.",
              file=sys.stderr)
        return 1080
    try:
        r = subprocess.run(
            [ffprobe, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=height', '-of', 'json',
             str(video_path)],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(r.stdout)
        height = int(data['streams'][0]['height'])
        if height <= 0:
            print(f"  WARNING: ffprobe returned invalid height ({height}); assuming 1080p.",
                  file=sys.stderr)
            return 1080
        return height
    except Exception as e:
        print(f"  WARNING: ffprobe failed ({e}); assuming 1080p for font scaling.",
              file=sys.stderr)
        return 1080


def scale_params(height: int, bilingual: bool, dual: bool) -> tuple[int, int]:
    """Return (font_size, margin_v) scaled to video height.

    Base design is 1080p. Values scale linearly, clamped to sane ranges.
    Outline style reads lighter than boxes, so the dual-layer fonts are a
    touch smaller than the old boxed defaults.
    """
    if bilingual or dual:
        # Two lines: smaller font, low bottom margin (EN stacks above ZH)
        base_font = 18
        base_margin = 28
    else:
        base_font = 24
        base_margin = 28

    scale = height / 1080.0
    font_size = max(12, int(round(base_font * scale)))
    margin_v = max(20, int(round(base_margin * scale)))
    return font_size, margin_v


# ── font detection ─────────────────────────────────────────────────

_CJK_FONT_CANDIDATES = [
    # Windows
    'Microsoft YaHei', 'Microsoft YaHei UI', 'SimHei', 'SimSun',
    # macOS
    'PingFang SC', 'Heiti SC', 'STHeiti',
    # Linux
    'Noto Sans CJK SC', 'Noto Sans SC', 'WenQuanYi Micro Hei', 'WenQuanYi Zen Hei',
]


def detect_cjk_font() -> str | None:
    """Try to find an installed CJK font using fc-list (Linux/macOS) or
    Windows font directory check."""
    # Linux / macOS: fc-list
    fc_list = shutil.which('fc-list')
    if fc_list:
        try:
            r = subprocess.run([fc_list, ':', 'family'],
                               capture_output=True, text=True, timeout=10)
            families = set()
            for line in r.stdout.splitlines():
                for fam in line.split(','):
                    families.add(fam.strip())
            for candidate in _CJK_FONT_CANDIDATES:
                if candidate in families:
                    return candidate
        except Exception:
            pass

    # Windows: check Fonts directory for common CJK font files
    if sys.platform == 'win32':
        fonts_dir = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
        win_font_map = {
            'msyh.ttc': 'Microsoft YaHei',
            'msyhbd.ttc': 'Microsoft YaHei',
            'msyhl.ttc': 'Microsoft YaHei UI',
            'simhei.ttf': 'SimHei',
            'simsun.ttc': 'SimSun',
        }
        for filename, font_name in win_font_map.items():
            if (fonts_dir / filename).exists():
                return font_name

    return None


# ── ffmpeg filter helpers ──────────────────────────────────────────

def _escape_srt_path(path: str) -> str:
    """Escape a file path for ffmpeg's subtitles filter.

    Converts Windows backslashes to forward slashes, then escapes the
    characters that are special to ffmpeg's filtergraph parser:
    : ' , ;
    """
    p = Path(path).resolve()
    s = str(p).replace('\\', '/')
    # Order matters: escape backslash-like and colon first, then quotes/commas/semicolons
    s = s.replace(':', '\\:')
    s = s.replace("'", "\\'")
    s = s.replace(',', '\\,')
    s = s.replace(';', '\\;')
    return s


def _build_style(
    font_size: int,
    font_name: str,
    position: str,
    margin_v: int,
    primary_colour: str = '&H00FFFFFF',   # white
    outline_colour: str = '&H00000000',   # black outline
    back_colour: str = '&H80000000',      # semi-transparent shadow/box
    outline: int = 3,
    shadow: int = 1,
    border_style: int = 1,                # 1=outline+shadow, 3=opaque box
    line_spacing: int = 0,
    bold: int = 0,
) -> str:
    """Build the force_style string for ffmpeg's subtitles filter."""
    alignment_map = {'bottom': 2, 'top': 8, 'center': 5}
    alignment = alignment_map.get(position, 2)

    parts = [
        f"FontSize={font_size}",
        f"FontName={font_name}",
        f"PrimaryColour={primary_colour}",
        f"OutlineColour={outline_colour}",
        f"BackColour={back_colour}",
        f"BorderStyle={border_style}",
        f"Outline={outline}",
        f"Shadow={shadow}",
        f"Alignment={alignment}",
        f"MarginV={margin_v}",
        f"Bold={bold}",
    ]
    if line_spacing:
        parts.append(f"LineSpacing={line_spacing}")

    return ','.join(parts)


def _build_single_filter(
    srt_path: Path,
    font_size: int,
    font_name: str,
    position: str,
    margin_v: int,
    bilingual: bool,
    border_style: int = 1,
) -> str:
    """Build a single-layer subtitles filter."""
    escaped = _escape_srt_path(str(srt_path))
    line_spacing = -1 if bilingual else 0
    style = _build_style(
        font_size=font_size,
        font_name=font_name,
        position=position,
        margin_v=margin_v,
        outline=3,
        shadow=1,
        border_style=border_style,
        line_spacing=line_spacing,
    )
    return f"subtitles='{escaped}':force_style='{style}'"


def _build_dual_filter(
    en_srt_path: Path,
    zh_srt_path: Path,
    font_size: int,
    font_name: str,
    margin_v: int,
    position: str = 'bottom',
    border_style: int = 1,
) -> str:
    """Build a dual-layer filter: English (smaller, lighter) + Chinese (larger, white).

    Default look (border_style=1) is classic fansub style: white text with a
    black outline and a soft shadow, no opaque boxes — much lighter on the
    eyes than boxed text. border_style=3 restores the old semi-transparent
    box look.

    position controls where the pair sits:
      - bottom: Chinese at bottom margin, English above it
      - top:    Chinese at top margin, English below it
      - center: falls back to bottom layout (ASS vertical centering does not
                support per-line vertical offset predictably)
    """
    en_escaped = _escape_srt_path(str(en_srt_path))
    zh_escaped = _escape_srt_path(str(zh_srt_path))
    # Tight line gap: EN sits just above the ZH line (~10px clearance at 1080p)
    line_gap = max(6, int(font_size * 1.15))

    if position == 'top':
        zh_margin = margin_v
        en_margin = margin_v + line_gap
        align_position = 'top'
    elif position == 'center':
        # Center alignment (ASS Alignment=5) ignores MarginV for vertical
        # positioning, so we cannot offset the two lines independently.
        # Fall back to bottom layout for a predictable two-line stack.
        zh_margin = margin_v
        en_margin = margin_v + line_gap
        align_position = 'bottom'
    else:  # bottom
        zh_margin = margin_v
        en_margin = margin_v + line_gap
        align_position = 'bottom'

    # English line: ~72% size, soft light grey, thin outline
    en_style = _build_style(
        font_size=max(9, int(font_size * 0.72)),
        font_name=font_name,
        position=align_position,
        margin_v=en_margin,
        primary_colour='&H00E8E8E8',
        outline=2,
        shadow=1,
        border_style=border_style,
        back_colour='&H90000000',
    )

    # Chinese line: full size, solid white, stronger outline
    zh_style = _build_style(
        font_size=font_size,
        font_name=font_name,
        position=align_position,
        margin_v=zh_margin,
        primary_colour='&H00FFFFFF',
        outline=3,
        shadow=1,
        border_style=border_style,
        back_colour='&H80000000',
    )

    return (
        f"subtitles='{en_escaped}':force_style='{en_style}',"
        f"subtitles='{zh_escaped}':force_style='{zh_style}'"
    )


# ── encoder selection ──────────────────────────────────────────────

# x264 preset → NVENC p-preset (p1 fastest / p7 best quality)
_NVENC_PRESET_MAP = {
    'ultrafast': 'p1', 'superfast': 'p2', 'veryfast': 'p3', 'faster': 'p3',
    'fast': 'p4', 'medium': 'p5', 'slow': 'p6', 'slower': 'p7', 'slowest': 'p7',
}


def _select_encoder(ffmpeg: str, encoder: str) -> tuple[str, str]:
    """Resolve requested encoder to (ffmpeg codec, human-readable label).

    'auto' probes h264_nvenc once and falls back to libx264. Forcing nvenc
    when the probe fails is a hard error (exit 1) so the user knows why.
    """
    want = (encoder or 'auto').strip().lower()
    if want in ('cpu', 'libx264', 'x264'):
        return 'libx264', 'libx264 (CPU)'
    if want in ('nvenc', 'h264_nvenc', 'gpu'):
        if not _nvenc_available(ffmpeg):
            print("ERROR: --encoder nvenc requested, but h264_nvenc is not "
                  "available (no NVIDIA GPU/driver, or an ffmpeg build "
                  "without NVENC support).", file=sys.stderr)
            sys.exit(1)
        return 'h264_nvenc', 'h264_nvenc (NVIDIA GPU)'
    if _nvenc_available(ffmpeg):
        return 'h264_nvenc', 'h264_nvenc (NVIDIA GPU, auto-detected)'
    return 'libx264', 'libx264 (CPU, NVENC unavailable)'


# ── main burn logic ────────────────────────────────────────────────

def burn_subtitles(
    video_path: Path,
    srt_path: Path | None,
    output_path: Path,
    font_size: int | None = None,
    font_name: str | None = None,
    position: str = 'bottom',
    margin_v: int | None = None,
    bilingual: bool = False,
    dual_en: Path | None = None,
    dual_zh: Path | None = None,
    crf: int = 23,
    preset: str = 'medium',
    encoder: str = 'auto',
    style: str = 'outline',
) -> Path:
    """Burn subtitles into video. Returns output path."""
    ffmpeg = _check_tool('ffmpeg')

    # Auto-detect CJK font if not specified
    if not font_name:
        font_name = detect_cjk_font() or 'Arial'
        print(f"  Font: {font_name} (auto-detected)", file=sys.stderr)

    # Auto-scale font size & margin based on video resolution
    height = get_video_height(video_path)
    dual = dual_en is not None and dual_zh is not None
    if font_size is None or margin_v is None:
        auto_fs, auto_mv = scale_params(height, bilingual, dual)
        if font_size is None:
            font_size = auto_fs
        if margin_v is None:
            margin_v = auto_mv
    print(f"  Video height: {height}px → font-size={font_size}, margin-v={margin_v}",
          file=sys.stderr)

    # Build filter chain
    border_style = 3 if style == 'box' else 1
    if dual:
        vf = _build_dual_filter(dual_en, dual_zh, font_size, font_name,
                                margin_v, position, border_style)
        srt_label = f"{dual_en.name} + {dual_zh.name}"
    else:
        if srt_path is None:
            print("ERROR: No subtitle file provided.", file=sys.stderr)
            sys.exit(1)
        vf = _build_single_filter(srt_path, font_size, font_name,
                                  position, margin_v, bilingual, border_style)
        srt_label = srt_path.name

    codec, enc_label = _select_encoder(ffmpeg, encoder)
    print(f"  Encoder: {enc_label}", file=sys.stderr)

    cmd = [ffmpeg, '-y', '-i', str(video_path), '-vf', vf]
    if codec == 'h264_nvenc':
        # NVENC has no CRF; -rc vbr + -cq + -b:v 0 is its constant-quality
        # equivalent. x264 preset names map onto NVENC p1-p7.
        nv_preset = _NVENC_PRESET_MAP.get(preset.lower(), 'p5')
        cmd += ['-c:v', codec, '-preset', nv_preset,
                '-rc', 'vbr', '-cq', str(crf), '-b:v', '0']
    else:
        cmd += ['-c:v', codec, '-crf', str(crf), '-preset', preset]
    cmd += ['-c:a', 'copy', '-movflags', '+faststart', str(output_path)]

    print(f"\nBurning subtitles into video...", file=sys.stderr)
    print(f"  Video:   {video_path.name}", file=sys.stderr)
    print(f"  SRT:     {srt_label}", file=sys.stderr)
    print(f"  Output:  {output_path.name}", file=sys.stderr)
    if dual:
        print(f"  Mode:    dual-layer (EN top / ZH bottom)", file=sys.stderr)
    elif bilingual:
        print(f"  Mode:    bilingual (two-line)", file=sys.stderr)

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
    ap.add_argument('srt', nargs='?', default=None,
                    help='SRT subtitle file (not needed with --dual)')
    ap.add_argument('output', nargs='?', default=None,
                    help='Output video path (default: <name>_subtitled.mp4)')
    ap.add_argument('--font-size', type=int, default=None,
                    help='Subtitle font size (auto-scaled to resolution if omitted)')
    ap.add_argument('--font', default=None,
                    help='Font name (auto-detects CJK font if omitted)')
    ap.add_argument('--position', default='bottom',
                    choices=['bottom', 'top', 'center'],
                    help='Subtitle position (default: bottom)')
    ap.add_argument('--margin-v', type=int, default=None,
                    help='Vertical margin in pixels (auto-scaled if omitted)')
    ap.add_argument('--bilingual', action='store_true',
                    help='Optimise styling for bilingual SRT (two-line entries)')
    ap.add_argument('--dual', nargs=2, metavar=('EN_SRT', 'ZH_SRT'),
                    default=None,
                    help='Dual-layer mode: English SRT on top, Chinese SRT below')
    ap.add_argument('--crf', type=int, default=23,
                    help='x264 CRF / NVENC CQ value (default: 23)')
    ap.add_argument('--preset', default='medium',
                    help='x264 preset (default: medium)')
    ap.add_argument('--encoder', default='auto',
                    choices=['auto', 'libx264', 'nvenc'],
                    help='Video encoder: auto uses NVIDIA NVENC when '
                         'available, else libx264 (default: auto)')
    ap.add_argument('--style', default='outline', choices=['outline', 'box'],
                    help="Subtitle look: outline (white text with black "
                         "outline + soft shadow, default) or box "
                         "(semi-transparent boxes, old style)")
    args = ap.parse_args()

    video_path = Path(args.video).resolve()
    if not video_path.exists():
        print(f"ERROR: Video not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    srt_path = None
    dual_en = dual_zh = None

    if args.dual:
        dual_en = Path(args.dual[0]).resolve()
        dual_zh = Path(args.dual[1]).resolve()
        for p, label in [(dual_en, 'English SRT'), (dual_zh, 'Chinese SRT')]:
            if not p.exists():
                print(f"ERROR: {label} not found: {p}", file=sys.stderr)
                sys.exit(1)
    else:
        if not args.srt:
            print("ERROR: Provide an SRT file, or use --dual EN ZH.", file=sys.stderr)
            sys.exit(1)
        srt_path = Path(args.srt).resolve()
        if not srt_path.exists():
            print(f"ERROR: SRT not found: {srt_path}", file=sys.stderr)
            sys.exit(1)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        stem = video_path.stem
        if args.dual:
            suffix = '_dual'
        elif args.bilingual:
            suffix = '_bilingual'
        else:
            suffix = '_subtitled'
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
        dual_en=dual_en,
        dual_zh=dual_zh,
        crf=args.crf,
        preset=args.preset,
        encoder=args.encoder,
        style=args.style,
    )


if __name__ == '__main__':
    main()
