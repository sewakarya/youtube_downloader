from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from yt_dlp import YoutubeDL


_LIKELY_YT_URL_RE = re.compile(r"^https?://")


def _prompt_url() -> str:
    while True:
        url = input("Paste YouTube link: ").strip()
        if not url:
            continue
        if not _LIKELY_YT_URL_RE.search(url):
            print("Please paste a full URL (starting with http:// or https://).", file=sys.stderr)
            continue
        return url


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="youtube-downloader",
        description="Download a YouTube video into a local Vid/ folder.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="YouTube URL. If omitted, the program will prompt for it.",
    )
    parser.add_argument(
        "--output-dir",
        default="Vid",
        help="Directory to download into (default: Vid).",
    )
    args = parser.parse_args()

    url = (args.url or "").strip() or _prompt_url()

    vid_dir = (Path.cwd() / args.output_dir).resolve()
    vid_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "outtmpl": str(vid_dir / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "ignoreerrors": False,
        "quiet": False,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"Download failed: {e}", file=sys.stderr)
        raise SystemExit(1) from e

