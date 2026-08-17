#!/usr/bin/env python3
"""SRT subtitle utilities: parse, write, merge bilingual.

Works standalone on any Python 3.8+. No external dependencies.
Used by download_and_transcribe.py, burn_subtitles.py, and by the
agent directly when creating translated / bilingual SRT files.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Segment:
    """One subtitle entry."""
    index: int
    start: float          # seconds
    end: float            # seconds
    text: str
    secondary: Optional[str] = None  # second language line (bilingual)

    @property
    def start_ts(self) -> str:
        return _seconds_to_ts(self.start)

    @property
    def end_ts(self) -> str:
        return _seconds_to_ts(self.end)


# ── timestamp helpers ──────────────────────────────────────────────

_TS_RE = re.compile(
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})'
)


def _seconds_to_ts(seconds: float) -> str:
    """float seconds → 'HH:MM:SS,mmm'"""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:          # rounding overflow
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_to_seconds(ts: str) -> float:
    """'HH:MM:SS,mmm' or 'HH:MM:SS.mmm' → float seconds"""
    ts = ts.strip().replace(',', '.')
    parts = ts.split(':')
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(ts)


# ── parse ──────────────────────────────────────────────────────────

def parse_srt(content: str) -> List[Segment]:
    """Parse SRT text into a list of Segment objects.

    Handles multi-line text, BOM, CRLF, and extra blank lines.
    """
    # strip BOM
    content = content.lstrip('\ufeff')
    # normalise line endings
    content = content.replace('\r\n', '\n').replace('\r', '\n')

    blocks = re.split(r'\n\s*\n', content.strip())
    segments: List[Segment] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split('\n')

        # first line might be index, or might be timestamp if index missing
        idx = 1
        ts_line_idx = 0
        if lines[0].strip().isdigit():
            idx = int(lines[0].strip())
            ts_line_idx = 1

        if ts_line_idx >= len(lines):
            continue

        ts_line = lines[ts_line_idx].strip()
        m = re.match(
            r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})',
            ts_line,
        )
        if not m:
            continue

        start = _ts_to_seconds(m.group(1))
        end = _ts_to_seconds(m.group(2))
        text_lines = lines[ts_line_idx + 1:]
        text = '\n'.join(t.rstrip() for t in text_lines if t.strip())

        segments.append(Segment(
            index=idx,
            start=start,
            end=end,
            text=text,
        ))

    # re-number sequentially
    for i, seg in enumerate(segments, 1):
        seg.index = i

    return segments


def parse_srt_file(path: str | Path) -> List[Segment]:
    """Read an SRT file and parse it."""
    p = Path(path)
    content = p.read_text(encoding='utf-8-sig')
    return parse_srt(content)


# ── write ──────────────────────────────────────────────────────────

def format_srt(segments: List[Segment]) -> str:
    """Render segments to SRT text."""
    parts: List[str] = []
    for seg in segments:
        block = f"{seg.index}\n"
        block += f"{seg.start_ts} --> {seg.end_ts}\n"
        if seg.secondary:
            block += f"{seg.text}\n{seg.secondary}\n"
        else:
            block += f"{seg.text}\n"
        parts.append(block)
    return '\n'.join(parts)


def write_srt(segments: List[Segment], path: str | Path) -> Path:
    """Write segments to an SRT file. Returns the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(format_srt(segments), encoding='utf-8')
    return p


# ── bilingual merge ────────────────────────────────────────────────

def merge_bilingual(
    primary: List[Segment],
    secondary: List[Segment],
) -> List[Segment]:
    """Merge two SRT segment lists into a bilingual SRT.

    Uses primary segments' timestamps. Secondary text is attached to
    the matching segment by index (or by closest timestamp if counts differ).
    """
    if len(secondary) == len(primary):
        for p, s in zip(primary, secondary):
            p.secondary = s.text
        return primary

    # fallback: match by closest start time
    sec_starts = [s.start for s in secondary]
    for p in primary:
        best_idx = min(
            range(len(sec_starts)),
            key=lambda i: abs(sec_starts[i] - p.start),
        )
        p.secondary = secondary[best_idx].text
    return primary


def create_bilingual_srt(
    primary_path: str | Path,
    secondary_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Create a bilingual SRT from two SRT files."""
    primary = parse_srt_file(primary_path)
    secondary = parse_srt_file(secondary_path)
    merged = merge_bilingual(primary, secondary)
    return write_srt(merged, output_path)


# ── CLI ────────────────────────────────────────────────────────────

def _cli():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  srt_utils.py parse    <file.srt>          # print parsed segments")
        print("  srt_utils.py bilingual <en.srt> <zh.srt> <out.srt>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'parse':
        segs = parse_srt_file(sys.argv[2])
        for s in segs:
            print(f"[{s.index}] {s.start_ts} --> {s.end_ts}")
            print(f"    {s.text}")
            print()

    elif cmd == 'bilingual':
        if len(sys.argv) < 5:
            print("Usage: srt_utils.py bilingual <en.srt> <zh.srt> <out.srt>")
            sys.exit(1)
        out = create_bilingual_srt(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"OK  bilingual SRT written: {out}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    _cli()
