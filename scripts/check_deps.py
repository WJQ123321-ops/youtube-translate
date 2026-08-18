#!/usr/bin/env python3
"""Check and optionally install dependencies for the youtube-translate skill.

Checks:
  1. yt-dlp          (CLI, nightly recommended for YouTube PO Token support)
  2. ffmpeg          (CLI)
  3. faster-whisper  (Python package)
  4. deno            (CLI, required by yt-dlp for YouTube PO Token generation)

Usage:
  python check_deps.py              # check only, report status
  python check_deps.py --install    # check + auto-install missing deps
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from importlib import import_module

# Fix Windows console encoding so ✓/✗/⚠/→/— don't crash on GBK terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def check_cli(name: str) -> bool:
    return shutil.which(name) is not None


def check_python_pkg(pkg: str) -> bool:
    try:
        import_module(pkg)
        return True
    except ImportError:
        return False


def get_version(name: str) -> str:
    try:
        r = subprocess.run([name, '--version'],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip().split('\n')[0] if r.stdout else r.stderr.strip().split('\n')[0]
    except Exception:
        return '?'


def get_python_pkg_version(pkg: str) -> str:
    try:
        mod = import_module(pkg)
        return getattr(mod, '__version__', '?')
    except Exception:
        return '?'


def install_cli(pip_name: str, cli_name: str) -> bool:
    """Install a CLI tool via pip."""
    print(f"  Installing {pip_name} via pip...")
    r = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', pip_name],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  FAILED: {r.stderr[-500:]}", file=sys.stderr)
        return False
    return shutil.which(cli_name) is not None


def install_python_pkg(pip_name: str, import_name: str) -> bool:
    """Install a Python package via pip."""
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


def detect_windows_proxy() -> str | None:
    """Detect system proxy on Windows (registry Internet Settings)."""
    if sys.platform != 'win32':
        return None
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
            return server
        winreg.CloseKey(key)
    except Exception:
        pass
    return None


def check_yt_dlp_nightly() -> tuple[bool, str]:
    """Check if yt-dlp is a recent enough version (2026.08+ recommended)."""
    if not check_cli('yt-dlp'):
        return False, ''
    ver = get_version('yt-dlp')
    # Nightly versions look like 2026.08.17.073947
    # Stable versions look like 2026.07.04
    # We recommend 2026.08+ for PO Token support
    try:
        date_part = ver.split('.')
        year = int(date_part[0])
        month = int(date_part[1]) if len(date_part) > 1 else 0
        is_recent = (year > 2026) or (year == 2026 and month >= 8)
        return is_recent, ver
    except Exception:
        return True, ver  # can't parse, assume OK


def main():
    ap = argparse.ArgumentParser(description='Check/install youtube-translate dependencies')
    ap.add_argument('--install', action='store_true',
                    help='Auto-install missing dependencies')
    args = ap.parse_args()

    print("=" * 60)
    print("  youtube-translate — Dependency Check")
    print("=" * 60)

    # --- Core dependencies ---
    deps = [
        ('yt-dlp',          check_cli,        'yt-dlp',          install_cli,        'yt-dlp',         'yt-dlp',         'yt-dlp'),
        ('ffmpeg',          check_cli,        'ffmpeg',          None,               None,             None,             'ffmpeg'),
        ('faster-whisper',  check_python_pkg, 'faster_whisper',  install_python_pkg, 'faster-whisper', 'faster-whisper', 'faster_whisper'),
    ]

    all_ok = True
    for display, check_fn, check_arg, install_fn, install_arg, pip_name, name in deps:
        ok = check_fn(check_arg)
        status = "✓ OK" if ok else "✗ MISSING"
        ver = ""
        if ok:
            if check_fn == check_cli:
                ver = get_version(name)
            else:
                ver = f"v{get_python_pkg_version(name)}"
        print(f"  {status:12s}  {display:20s}  {ver}")

        if not ok:
            if args.install and install_fn is not None:
                print(f"  → Attempting to install {display}...")
                if install_fn(install_arg, name):
                    # Re-check after install
                    ok = check_fn(check_arg)
                    if ok:
                        print(f"  ✓ Installed {display} successfully!")
                    else:
                        print(f"  ✗ Install reported success but {name} still not found on PATH")
                else:
                    print(f"  ✗ Failed to install {display}")
            elif not args.install:
                if display == 'ffmpeg':
                    print(f"    → Download from https://ffmpeg.org/download.html")
                    print(f"       Or: winget install ffmpeg  /  brew install ffmpeg  /  apt install ffmpeg")
                else:
                    print(f"    → pip install {pip_name}")

        if not ok:
            all_ok = False

    # --- deno (required for YouTube PO Token) ---
    deno_ok = check_cli('deno')
    deno_ver = get_version('deno') if deno_ok else ''
    deno_status = "✓ OK" if deno_ok else "⚠ MISSING"
    print(f"  {deno_status:12s}  {'deno':20s}  {deno_ver}")
    if not deno_ok:
        print(f"    → deno is required by yt-dlp for YouTube PO Token generation.")
        print(f"       Without it, YouTube video downloads may fail with HTTP 403.")
        if sys.platform == 'win32':
            print(f"       Install: winget install DenoLand.Deno")
        elif sys.platform == 'darwin':
            print(f"       Install: brew install deno")
        else:
            print(f"       Install: curl -fsSL https://deno.land/install.sh | sh")
        print(f"       Or download from https://github.com/denoland/deno/releases")
        if args.install:
            if sys.platform == 'win32':
                print(f"  → Attempting to install deno via winget...")
                r = subprocess.run(
                    ['winget', 'install', 'DenoLand.Deno',
                     '--accept-package-agreements', '--accept-source-agreements'],
                    capture_output=True, text=True,
                )
                if r.returncode == 0:
                    deno_ok = check_cli('deno')
                    if deno_ok:
                        print(f"  ✓ Installed deno successfully!")
                    else:
                        print(f"  ✗ winget reported success but deno still not found (may need a new shell)")
                else:
                    print(f"  ✗ Failed to install deno via winget. Please install manually.")
            else:
                print(f"  → Auto-install only supported on Windows (winget). Please install deno manually.")

    if not deno_ok:
        all_ok = False

    # --- yt-dlp version check ---
    ytdlp_recent, ytdlp_ver = check_yt_dlp_nightly()
    if ytdlp_recent:
        print(f"  ✓ OK          yt-dlp version      {ytdlp_ver} (recent)")
    else:
        print(f"  ⚠ OUTDATED    yt-dlp version      {ytdlp_ver}")
        print(f"    → YouTube now requires PO Token; yt-dlp nightly (2026.08+) recommended.")
        print(f"       Download: https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest")
        all_ok = False

    # --- Proxy detection ---
    print()
    proxy = detect_windows_proxy()
    if proxy:
        print(f"  ℹ System proxy detected: {proxy}")
        print(f"    (Will be used automatically for YouTube downloads)")
    else:
        env_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
        if env_proxy:
            print(f"  ℹ Environment proxy: {env_proxy}")
        else:
            print(f"  ℹ No system proxy detected. If YouTube is blocked in your region,")
            print(f"    set HTTPS_PROXY or use --proxy when downloading.")

    print("=" * 60)
    if all_ok:
        print("  All dependencies satisfied! ✓")
    elif args.install:
        print("  Some dependencies could not be auto-installed.")
        print("  See messages above for manual installation steps.")
    else:
        print("  Missing or outdated dependencies detected.")
        print("  Run with --install to auto-install pip packages,")
        print("  or install deno/ffmpeg manually as shown above.")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
