"""Step 1b: 전체 영상 Whisper 전사 + 음악·무음 구간 환각 문장 제거."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from typing import Callable

from config import settings
from pipeline.context import PipelineContext
from providers.ffmpeg import extract_audio
from providers.whisper_client import transcribe_full

_log = logging.getLogger(__name__)

# 같은 문장이 이 횟수 이상 나오면 모두 제외 (찬양 후렴, 음악 구간에서 반복되는 환각 문구)
REPEAT_LIMIT = 3


def _normalize(text: str) -> str:
    """공백·문장부호를 뺀 비교용 문자열."""
    return re.sub(r"[\W_]+", "", text)


def _is_speech(seg: dict, counts: Counter) -> bool:
    """실제 말소리로 볼 수 있는 세그먼트인지 판단한다.

    음악·무음 구간에서 Whisper는 "이 영상은 유료광고를 포함하고 있습니다." 같은
    문장을 확신도 높게 지어내므로, avg_logprob보다 no_speech_prob와 반복 여부를 본다.
    """
    key = _normalize(seg["text"])
    if not key or key.isdigit():
        return False
    if seg.get("no_speech_prob", 0.0) >= settings.WHISPER_NO_SPEECH_THRESHOLD:
        return False
    return counts[key] < REPEAT_LIMIT


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

    # 각 세그먼트에 speech 표시 — transcript.json에는 전부 남기고, 파이프라인에는 말소리만 넘긴다
    segments = result["segments"]
    counts = Counter(_normalize(s["text"]) for s in segments)
    for s in segments:
        s["speech"] = _is_speech(s, counts)

    ctx.transcript_text = result["text"]
    ctx.transcript_segments = [s for s in segments if s["speech"]]
    dropped = len(segments) - len(ctx.transcript_segments)
    if dropped:
        _log.info("음악·무음 환각 의심 문장 %d/%d개 제외", dropped, len(segments))

    # 전사 결과 저장
    transcript_path = ctx.project_dir / "transcript.json"
    transcript_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    msg = f"{len(ctx.transcript_segments)}개 문장 구간 감지 완료"
    if dropped:
        msg += f" (음악·무음 {dropped}개 제외)"
    ctx.update_progress(2, 1.0, msg)
    notify()
