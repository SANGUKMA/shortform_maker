"""Step 1: 영상 다운로드 (subprocess 기반 yt-dlp CLI 호출)."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from config import settings, BASE_DIR
from pipeline.context import PipelineContext

COOKIES_PATH = BASE_DIR / "cookies.txt"


def _cookies_args() -> list[str]:
    """cookies.txt가 있으면 --cookies 인자를 반환."""
    if COOKIES_PATH.exists():
        return ["--cookies", str(COOKIES_PATH)]
    return []


async def run(ctx: PipelineContext, notify: Callable) -> None:
    if ctx.is_youtube_url:
        await _download_youtube(ctx, notify)
    else:
        await _copy_local(ctx, notify)


async def _download_youtube(ctx: PipelineContext, notify: Callable) -> None:
    output_template = str(ctx.project_dir / "source.%(ext)s")
    max_res = min(settings.MAX_RESOLUTION, 720)

    # 1단계: 메타데이터 먼저 가져오기 (다운로드 없이)
    ctx.update_progress(1, 0.05, "영상 정보 확인 중...")
    notify()

    meta_cmd = [
        "yt-dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        *_cookies_args(),
        "--dump-json", "--no-download",
        ctx.source,
    ]
    loop = asyncio.get_event_loop()
    meta_result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(meta_cmd, capture_output=True, text=True, timeout=60),
    )
    if meta_result.returncode == 0 and meta_result.stdout.strip():
        try:
            info = json.loads(meta_result.stdout)
            ctx.video_title = info.get("title", "Untitled")
            ctx.video_duration = info.get("duration", 0)
        except json.JSONDecodeError:
            pass  # 메타데이터 실패는 무시, 다운로드 후 파일에서 확인

    ctx.update_progress(1, 0.1, f'"{ctx.video_title}" 다운로드 시작...')
    notify()

    # 2단계: 영상 다운로드 (subprocess)
    dl_cmd = [
        "yt-dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        *_cookies_args(),
        "-f", f"bestvideo[height<={max_res}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--retries", "10",
        "--fragment-retries", "10",
        "-o", output_template,
        "--no-warnings",
        ctx.source,
    ]
    dl_result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(dl_cmd, capture_output=True, text=True, timeout=600),
    )

    if dl_result.returncode != 0:
        raise RuntimeError(f"yt-dlp 다운로드 실패:\n{dl_result.stderr[-1000:]}")

    # 다운로드된 파일 찾기
    mp4_files = list(ctx.project_dir.glob("source.mp4"))
    if not mp4_files:
        mp4_files = [f for f in ctx.project_dir.glob("source.*") if f.suffix not in (".part", ".srt")]
    if not mp4_files:
        raise FileNotFoundError("다운로드된 영상 파일을 찾을 수 없습니다.")
    ctx.source_path = mp4_files[0]

    ctx.update_progress(1, 0.8, "다운로드 완료")
    notify()

    # 3단계: 자막 별도 다운로드 (실패해도 무시)
    ctx.update_progress(1, 0.9, "자막 다운로드 시도 중...")
    notify()
    await _try_download_subtitles(ctx, loop)

    ctx.update_progress(1, 1.0, "다운로드 완료")
    notify()


async def _try_download_subtitles(ctx: PipelineContext, loop) -> None:
    """자막 다운로드를 시도한다. 실패해도 무시."""
    sub_cmd = [
        "yt-dlp",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        *_cookies_args(),
        "--write-auto-sub", "--write-sub",
        "--sub-lang", "ko,en",
        "--sub-format", "srt",
        "--skip-download",
        "-o", str(ctx.project_dir / "source.%(ext)s"),
        "--no-warnings",
        ctx.source,
    ]
    try:
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(sub_cmd, capture_output=True, text=True, timeout=60),
        )
        srt_files = list(ctx.project_dir.glob("source*.srt"))
        if srt_files:
            ctx.source_srt = srt_files[0]
    except Exception:
        pass


async def _copy_local(ctx: PipelineContext, notify: Callable) -> None:
    src = Path(ctx.source)
    if not src.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {src}")

    ctx.update_progress(1, 0.3, "로컬 파일 복사 중...")
    notify()

    dest = ctx.project_dir / f"source{src.suffix}"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, shutil.copy2, str(src), str(dest))

    ctx.source_path = dest
    ctx.video_title = src.stem

    from providers.ffmpeg import get_duration
    ctx.video_duration = int(get_duration(dest))

    ctx.update_progress(1, 1.0, "파일 준비 완료")
    notify()
