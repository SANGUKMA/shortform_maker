"""Step 1b: 전체 영상 Whisper 전사 (문장 경계 스냅용)."""
from __future__ import annotations

import asyncio
import json
from typing import Callable

from pipeline.context import PipelineContext
from providers.ffmpeg import extract_audio
from providers.whisper_client import transcribe_full


async def run(ctx: PipelineContext, notify: Callable) -> None:
    ctx.update_progress(2, 0.1, "전체 오디오 추출 중...")
    notify()

    audio_path = ctx.project_dir / "full_audio.wav"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, extract_audio, ctx.source_path, audio_path)
    ctx.full_audio_path = audio_path

    ctx.update_progress(2, 0.3, "Whisper 전사 중 (문장 경계 감지)...")
    notify()

    result = await loop.run_in_executor(None, transcribe_full, audio_path)

    ctx.transcript_text = result["text"]
    ctx.transcript_segments = result["segments"]

    # 전사 결과 저장
    transcript_path = ctx.project_dir / "transcript.json"
    transcript_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ctx.update_progress(2, 1.0, f"{len(ctx.transcript_segments)}개 문장 구간 감지 완료")
    notify()
