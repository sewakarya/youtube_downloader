from __future__ import annotations

import time
import threading
import uuid
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL


def _ffmpeg_available() -> bool:
    """Return True if ffmpeg is on PATH and executable."""
    return shutil.which("ffmpeg") is not None


# Repo root: .../youtube_downloader (this file lives in .../youtube_downloader/src/youtube_downloader/web.py)
APP_ROOT = Path(__file__).resolve().parents[2]


def _resolve_output_dir(raw: str) -> Path:
    if not raw.strip():
        raise ValueError("Output path is required.")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p)
    return p.resolve()


ProxyMode = Literal["auto", "direct", "custom"]


def _proxy_opts(mode: ProxyMode, proxy_url: str | None) -> dict[str, Any]:
    # yt-dlp option "proxy":
    # - absent/None: use system/env proxy behavior
    # - "" (empty string): force no proxy
    # - "http://..." or "socks5://...": use that proxy
    if mode == "auto":
        return {}
    if mode == "direct":
        return {"proxy": ""}
    if mode == "custom":
        if not proxy_url or not proxy_url.strip():
            raise ValueError("Custom proxy URL is required when proxy mode is 'custom'.")
        return {"proxy": proxy_url.strip()}
    raise ValueError(f"Unknown proxy mode: {mode}")


def _env_without_proxy() -> dict[str, str]:
    env = dict(os.environ)
    for k in list(env.keys()):
        if k.lower().endswith("_proxy") or k.lower() in {"all_proxy", "no_proxy"}:
            env.pop(k, None)
    return env


def _extract_info_subprocess(url: str, *, proxy_mode: ProxyMode, proxy_url: str | None) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "yt_dlp", "-J", "--no-playlist"]
    if proxy_mode == "direct":
        cmd += ["--proxy", ""]
    elif proxy_mode == "custom":
        if not proxy_url or not proxy_url.strip():
            raise ValueError("Custom proxy URL is required when proxy mode is 'custom'.")
        cmd += ["--proxy", proxy_url.strip()]
    cmd.append(url)

    p = subprocess.run(
        cmd,
        env=_env_without_proxy() if proxy_mode in ("direct", "custom") else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "yt-dlp failed").strip())
    return json.loads(p.stdout)


def _extract_info(url: str, *, proxy_mode: ProxyMode, proxy_url: str | None) -> dict[str, Any]:
    # Prefer subprocess for modes where we must ignore forced proxy env vars.
    if proxy_mode in ("direct", "custom"):
        return _extract_info_subprocess(url, proxy_mode=proxy_mode, proxy_url=proxy_url)
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        **_proxy_opts(proxy_mode, proxy_url),
    }
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def _available_heights(info: dict[str, Any]) -> list[int]:
    heights: set[int] = set()
    for f in info.get("formats") or []:
        h = f.get("height")
        if isinstance(h, int) and h > 0:
            heights.add(h)
    return sorted(heights, reverse=True)


class FormatsResponse(BaseModel):
    title: str | None = None
    heights: list[int] = Field(default_factory=list)


class DownloadRequest(BaseModel):
    url: str
    output_dir: str = Field(default="Vid")
    height: int | None = None  # If omitted: best available
    proxy_mode: ProxyMode = Field(default="auto")
    proxy_url: str | None = None


JobState = Literal["queued", "running", "done", "error"]


class JobStatus(BaseModel):
    id: str
    state: JobState
    message: str | None = None
    output_dir: str | None = None
    output_file: str | None = None


_jobs: dict[str, JobStatus] = {}
_jobs_lock = threading.Lock()


def _set_job(job_id: str, **updates: Any) -> None:
    with _jobs_lock:
        cur = _jobs[job_id]
        _jobs[job_id] = JobStatus(**{**cur.model_dump(), **updates})


def _build_format(height: int | None) -> str:
    """Return a yt-dlp format string appropriate for the environment.

    Prefers mp4 video + m4a audio so ffmpeg can remux into MP4 quickly
    without re-encoding.  Falls back to any format if mp4/m4a aren't
    available.  When ffmpeg is absent, requests a pre-muxed single file.
    """
    has_ffmpeg = _ffmpeg_available()
    if height is None:
        if has_ffmpeg:
            # Best mp4 video + best m4a audio → fast remux to .mp4
            # Fallback: any bestvideo+bestaudio (will be converted)
            return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
        return "best[ext=mp4]/best"
    else:
        if has_ffmpeg:
            return (
                f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]/best"
            )
        return f"best[height<={height}][ext=mp4]/best[height<={height}]/best"


def _run_download(job_id: str, req: DownloadRequest) -> None:
    try:
        _set_job(job_id, state="running", message="Starting download…")
        out_dir = _resolve_output_dir(req.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        started_at = time.time()

        fmt = _build_format(req.height)
        # Force .mp4 extension in the output template when ffmpeg is available
        # (it will remux/convert to mp4). Without ffmpeg, let yt-dlp decide.
        if _ffmpeg_available():
            outtmpl = str(out_dir / "%(title)s.mp4")
        else:
            outtmpl = str(out_dir / "%(title)s.%(ext)s")

        if req.proxy_mode in ("direct", "custom"):
            cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--no-playlist",
                "-f",
                fmt,
                "--merge-output-format", "mp4",
                "--recode-video", "mp4",
                "-o",
                outtmpl,
                "--restrict-filenames",
            ]
            if not _ffmpeg_available():
                cmd += ["--no-merge-output-format"]
            if req.proxy_mode == "direct":
                cmd += ["--proxy", ""]
            else:
                if not req.proxy_url or not req.proxy_url.strip():
                    raise ValueError("Custom proxy URL is required when proxy mode is 'custom'.")
                cmd += ["--proxy", req.proxy_url.strip()]
            cmd.append(req.url)

            p = subprocess.run(
                cmd,
                env=_env_without_proxy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if p.returncode != 0:
                raise RuntimeError((p.stderr or p.stdout or "yt-dlp failed").strip())
        else:
            ydl_opts = {
                "outtmpl": outtmpl,
                "format": fmt,
                "merge_output_format": "mp4",
                "noplaylist": True,
                "restrictfilenames": True,
                "windowsfilenames": True,
                "ignoreerrors": False,
                "quiet": False,
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
            }
            if not _ffmpeg_available():
                ydl_opts.pop("merge_output_format", None)
                ydl_opts.pop("postprocessors", None)
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([req.url])

        # Verification: find the output file.
        # Prefer files written/modified during this job (new downloads),
        # but also accept pre-existing files (yt-dlp skips re-downloading
        # files that already exist, which is still a success).
        candidates_new: list[Path] = []
        candidates_existing: list[Path] = []
        for fp in out_dir.iterdir():
            if not fp.is_file():
                continue
            if fp.name.endswith(".part"):
                continue
            try:
                st = fp.stat()
                if st.st_size == 0:
                    continue
                if st.st_mtime >= (started_at - 2):
                    candidates_new.append(fp)
                else:
                    candidates_existing.append(fp)
            except FileNotFoundError:
                continue

        candidates = candidates_new or candidates_existing
        output_file = str(max(candidates, key=lambda x: x.stat().st_size)) if candidates else None
        if output_file is None:
            _set_job(
                job_id,
                state="error",
                message="Download finished but no output file was found in the target folder.",
                output_dir=str(out_dir),
                output_file=None,
            )
            return

        _set_job(
            job_id,
            state="done",
            message="Download complete.",
            output_dir=str(out_dir),
            output_file=output_file,
        )
    except Exception as e:  # noqa: BLE001
        _set_job(job_id, state="error", message=str(e))


app = FastAPI(title="YouTube Downloader")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(APP_ROOT / "web" / "index.html")


@app.get("/api/formats", response_model=FormatsResponse)
def api_formats(url: str, proxy_mode: ProxyMode = "auto", proxy_url: str | None = None) -> FormatsResponse:
    try:
        info = _extract_info(url, proxy_mode=proxy_mode, proxy_url=proxy_url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)) from e

    return FormatsResponse(
        title=info.get("title"),
        heights=_available_heights(info),
    )


@app.post("/api/download", response_model=JobStatus)
def api_download(req: DownloadRequest) -> JobStatus:
    job_id = uuid.uuid4().hex
    status = JobStatus(id=job_id, state="queued", message="Queued.", output_dir=None)
    with _jobs_lock:
        _jobs[job_id] = status

    t = threading.Thread(target=_run_download, args=(job_id, req), daemon=True)
    t.start()
    return status


@app.post("/api/self-test", response_model=JobStatus)
def api_self_test(req: DownloadRequest) -> JobStatus:
    # Force a predictable default for the one-click self-test.
    forced = DownloadRequest(url=req.url, output_dir=req.output_dir or "Vid", height=req.height)
    return api_download(forced)


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def api_job(job_id: str) -> JobStatus:
    with _jobs_lock:
        st = _jobs.get(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return st


@app.get("/api/download-file/{job_id}")
def api_download_file(job_id: str) -> FileResponse:
    """Download the completed video file to the user's browser."""
    with _jobs_lock:
        st = _jobs.get(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    if st.state != "done":
        raise HTTPException(status_code=400, detail="Job is not complete yet")
    if not st.output_file:
        raise HTTPException(status_code=404, detail="No output file available")
    
    file_path = Path(st.output_file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="video/mp4",
    )


def main() -> None:
    uvicorn.run("youtube_downloader.web:app", host="127.0.0.1", port=8000, reload=True)

