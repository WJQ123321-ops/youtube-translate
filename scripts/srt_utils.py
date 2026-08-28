#!/usr/bin/env python3
"""SRT subtitle utilities: parse, write, merge bilingual.

Works standalone on any Python 3.8+. No external dependencies.
Used by download_and_transcribe.py, burn_subtitles.py, and by the
agent directly when creating translated / bilingual SRT files.
"""

from __future__ import annotations

import locale
import math
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

def _seconds_to_ts(seconds: float) -> str:
    """float seconds → 'HH:MM:SS,mmm'

    Uses total milliseconds so cascading carries (ms→s→m→h) are always
    correct, e.g. 59.9996 → 00:01:00,000 rather than 00:00:60,000.
    """
    if seconds is None or (isinstance(seconds, float) and (math.isnan(seconds) or math.isinf(seconds))):
        seconds = 0.0
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h = total_ms // 3600000
    total_ms %= 3600000
    m = total_ms // 60000
    total_ms %= 60000
    s = total_ms // 1000
    ms = total_ms % 1000
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
            r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})',
            ts_line,
        )
        if not m:
            continue

        # Validate minute/second ranges
        try:
            sh, sm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
            eh, em, es = int(m.group(5)), int(m.group(6)), int(m.group(7))
        except ValueError:
            continue
        if not (0 <= sm < 60 and 0 <= ss < 60 and 0 <= em < 60 and 0 <= es < 60):
            continue

        # zfill: SRT ms field is an integer count of milliseconds, so ",5" → 5ms
        start = _ts_to_seconds(f"{sh}:{sm}:{ss}.{m.group(4).zfill(3)}")
        end = _ts_to_seconds(f"{eh}:{em}:{es}.{m.group(8).zfill(3)}")
        if start > end:
            continue
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


def _get_system_encoding() -> str | None:
    """Best-effort detection of the system's legacy encoding.

    On Windows, uses GetACP() (returns e.g. 936 for GBK, 1252 for Latin-1)
    because locale.getpreferredencoding() may return 'utf-8' under Python's
    UTF-8 mode. On other platforms, falls back to locale.
    """
    if sys.platform == 'win32':
        try:
            import ctypes
            cp = ctypes.windll.kernel32.GetACP()
            return f'cp{cp}'
        except Exception:
            pass
    try:
        enc = locale.getpreferredencoding(False)
        return enc if enc else None
    except Exception:
        return None


def parse_srt_file(path: str | Path) -> List[Segment]:
    """Read an SRT file and parse it.

    Encoding detection strategy:
      1. If the file has a UTF-16 BOM (FF FE / FE FF), decode as utf-16.
      2. If the file has a UTF-8 BOM (EF BB BF), decode as utf-8-sig.
      3. Otherwise try utf-8-sig (handles BOM-less UTF-8), then the
         system default encoding (e.g. GBK on Chinese Windows).
      4. UTF-16 without BOM is not auto-detected (ambiguous); add a BOM
         or convert to UTF-8 if you have such a file.
    """
    p = Path(path)
    raw = p.read_bytes()

    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        encodings = ['utf-16']
    elif raw.startswith(b'\xef\xbb\xbf'):
        encodings = ['utf-8-sig']
    else:
        encodings = ['utf-8-sig', 'utf-8']
        sys_enc = _get_system_encoding()
        if sys_enc and sys_enc.lower() not in ('utf-8', 'utf-8-sig'):
            encodings.append(sys_enc)

    content = None
    for enc in encodings:
        try:
            content = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content is None:
        content = raw.decode('utf-8', errors='replace')

    return parse_srt(content)


# ── write ──────────────────────────────────────────────────────────

def format_srt(segments: List[Segment]) -> str:
    """Render segments to SRT text. Segments are re-numbered sequentially."""
    parts: List[str] = []
    for i, seg in enumerate(segments, 1):
        seg.index = i
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
    time_threshold: float = 2.0,
) -> List[Segment]:
    """Merge two SRT segment lists into a bilingual SRT.

    Uses primary segments' timestamps. Secondary text is attached to
    the matching segment by index (when counts match) or by closest
    start time within time_threshold (when counts differ).

    If secondary is empty, returns primary unchanged.
    """
    if not secondary:
        return primary

    if len(secondary) == len(primary):
        for p, s in zip(primary, secondary):
            p.secondary = s.text
        return primary

    # fallback: match by closest start time within threshold.
    # Track matched secondaries so one entry is never reused by two primaries.
    used: set = set()
    for p in primary:
        best_idx = -1
        best_diff = float('inf')
        for i, s in enumerate(secondary):
            if i in used:
                continue
            diff = abs(s.start - p.start)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        if best_idx >= 0 and best_diff <= time_threshold:
            p.secondary = secondary[best_idx].text
            used.add(best_idx)
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
