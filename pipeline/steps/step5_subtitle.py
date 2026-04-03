"""Step 5: Whisper 자막 생성 + FFmpeg burn-in."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Callable

from pipeline.context import PipelineContext
from providers.ffmpeg import burn_subtitles, extract_audio
from providers.whisper_client import transcribe_to_srt


async def run(ctx: PipelineContext, notify: Callable) -> None:
    total = len(ctx.short_paths)
    if total == 0:
        raise ValueError("자막을 적용할 숏폼이 없습니다.")

    ctx.final_paths = []
    loop = asyncio.get_event_loop()

    for i, (short_path, clip_path) in enumerate(zip(ctx.short_paths, ctx.clip_paths)):
        pct = i / total
        ctx.update_progress(6, pct, f"자막 {i+1}/{total} 생성 중...")
        notify()

        final_path = ctx.final_dir / f"final_{i+1:03d}.mp4"

        try:
            # 원본 클립에서 오디오 추출 → Whisper 전사
            audio_path = ctx.project_dir / f"audio_{i:03d}.wav"
            srt_path = ctx.project_dir / f"sub_{i:03d}.srt"

            await loop.run_in_executor(None, extract_audio, clip_path, audio_path)
            await loop.run_in_executor(None, transcribe_to_srt, audio_path, srt_path)

            # 숏폼에 자막 burn-in
            await loop.run_in_executor(None, burn_subtitles, short_path, final_path, srt_path)

            # 임시 파일 삭제
            audio_path.unlink(missing_ok=True)

        except Exception:
            # 자막 실패 시 숏폼을 그대로 최종 파일로 복사
            shutil.copy2(str(short_path), str(final_path))

        ctx.final_paths.append(final_path)

    ctx.update_progress(6, 1.0, f"{total}개 자막 처리 완료")
    notify()
