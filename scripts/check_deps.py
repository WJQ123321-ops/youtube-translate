#!/usr/bin/env python3
"""Check and optionally install dependencies for the youtube-translate skill.

Checks:
  1. yt-dlp          (CLI — verifies it actually runs, not just exists in PATH)
  2. ffmpeg          (CLI — verifies it actually runs)
  3. faster-whisper  (Python package)

Usage:
  python check_deps.py              # check only, report status
  python check_deps.py --install    # check + auto-install missing deps
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from importlib import import_module


def _run_version(name: str, flag: str = '--version') -> subprocess.CompletedProcess | None:
    """Run a tool's version command, trying --version then -version."""
    for f in (flag, '-version'):
        try:
            r = subprocess.run(
                [name, f],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                return r
        except Exception:
            continue
    return None


def check_cli(name: str, version_flag: str = '--version') -> bool:
    """Check that a CLI tool exists in PATH AND can run successfully."""
    if shutil.which(name) is None:
        return False
    r = _run_version(name, version_flag)
    if r is None:
        return False
    output = (r.stdout or '') + (r.stderr or '')
    for line in output.strip().splitlines():
        line = line.strip()
        if line and 'Traceback' not in line and not line.startswith('  File'):
            return True
    return False


def check_python_pkg(pkg: str) -> bool:
    try:
        import_module(pkg)
        return True
    except ImportError:
        return False


def get_version(name: str, version_flag: str = '--version') -> str:
    """Get a clean version string from a CLI tool's version output."""
    r = _run_version(name, version_flag)
    if r is None:
        return '?'
    for source in (r.stdout, r.stderr):
        if not source:
            continue
        for line in source.strip().splitlines():
            line = line.strip()
            if (line
                    and 'Traceback' not in line
                    and not line.startswith('  File')
                    and 'ModuleNotFoundError' not in line):
                return line
    return '?'


def get_python_pkg_version(pkg: str) -> str:
    try:
        mod = import_module(pkg)
        return getattr(mod, '__version__', '?')
    except Exception:
        return '?'


def install_cli(pip_name: str, cli_name: str) -> bool:
    """Install a CLI tool via pip, then verify it runs."""
    print(f"  Installing {pip_name} via pip...")
    r = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', pip_name],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  FAILED: {r.stderr[-500:]}", file=sys.stderr)
        return False
    return check_cli(cli_name)


def install_python_pkg(pip_name: str, import_name: str) -> bool:
    """Install a Python package via pip, then verify import."""
    print(f"  Installing {pip_name} via pip...")
    r = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', pip_name],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  FAILED: {r.stderr[-500:]}", file=sys.stderr)
        return False
    try:
        import_module(import_name)
        return True
    except ImportError:
        return False


def main():
    ap = argparse.ArgumentParser(description='Check/install youtube-translate dependencies')
    ap.add_argument('--install', action='store_true',
                    help='Auto-install missing dependencies')
    args = ap.parse_args()

    deps = [
        # (display_name, check_func, check_arg, version_flag, install_func, install_arg, pip_name, cli_or_import)
        ('yt-dlp',          check_cli,        'yt-dlp',         '--version', install_cli,        'yt-dlp',        'yt-dlp',        'yt-dlp'),
        ('ffmpeg',          check_cli,        'ffmpeg',         '-version',  None,               None,            None,            'ffmpeg'),
        ('faster-whisper',  check_python_pkg, 'faster_whisper', None,        install_python_pkg, 'faster-whisper','faster-whisper','faster_whisper'),
    ]

    print("=" * 55)
    print("  youtube-translate — Dependency Check")
    print("=" * 55)

    all_ok = True
    for display, check_fn, check_arg, version_flag, install_fn, install_arg, pip_name, name in deps:
        ok = check_fn(check_arg, version_flag) if version_flag else check_fn(check_arg)
        status = "✓ OK" if ok else "✗ MISSING"
        ver = ""
        if ok:
            if check_fn == check_cli:
                ver = get_version(name, version_flag)
            else:
                ver = f"v{get_python_pkg_version(name)}"
        print(f"  {status:12s}  {display:20s}  {ver}")

        if not ok:
            all_ok = False
            if args.install and install_fn:
                print(f"  → Attempting to install {display}...")
                if install_fn(install_arg, name):
                    print(f"  ✓ Installed {display} successfully!")
                    all_ok = True
                else:
                    print(f"  ✗ Failed to install {display}")
            elif not args.install:
                if display == 'ffmpeg':
                    print(f"    → Download from https://ffmpeg.org/download.html")
                    print(f"       Or: winget install ffmpeg  /  brew install ffmpeg  /  apt install ffmpeg")
                else:
                    print(f"    → pip install {pip_name}")

    print("=" * 55)
    if all_ok:
        print("  All dependencies satisfied! ✓")
    elif args.install:
        print("  Some dependencies could not be auto-installed.")
        print("  See messages above for manual installation steps.")
    else:
        print("  Missing dependencies detected. Run with --install to auto-install,")
        print("  or install manually as shown above.")
    print("=" * 55)

    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
