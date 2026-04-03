"""Step 2: Gemini AI 하이라이트 분석 + 문장 경계 스냅."""
from __future__ import annotations

import json
import logging
from typing import Callable

from pipeline.context import Highlight, PipelineContext
from providers.gemini import analyze_highlights

log = logging.getLogger(__name__)


def _ts_to_seconds(ts: str) -> float:
    """HH:MM:SS → seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0.0


def _seconds_to_ts(sec: float) -> str:
    """seconds → HH:MM:SS."""
    sec = max(0, sec)
    h = int(sec) // 3600
    m = (int(sec) % 3600) // 60
    s = int(sec) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _find_nearest(target: float, candidates: list[float], tolerance: float = 3.0) -> float | None:
    """tolerance 이내에서 target에 가장 가까운 값을 반환."""
    best = None
    best_diff = tolerance
    for c in candidates:
        diff = abs(c - target)
        if diff <= best_diff:
            best_diff = diff
            best = c
    return best


def _snap_boundaries(highlights: list[Highlight], segments: list[dict], tolerance: float = 3.0) -> None:
    """Gemini 타임스탬프를 Whisper 문장 경계에 스냅."""
    if not segments:
        return

    seg_starts = [s["start"] for s in segments]
    seg_ends = [s["end"] for s in segments]

    for h in highlights:
        orig_start = _ts_to_seconds(h.start)
        orig_end = _ts_to_seconds(h.end)

        # end → 가장 가까운 segment end로 스냅
        new_end = _find_nearest(orig_end, seg_ends, tolerance)
        # start → 가장 가까운 segment start로 스냅
        new_start = _find_nearest(orig_start, seg_starts, tolerance)

        final_start = new_start if new_start is not None else orig_start
        final_end = new_end if new_end is not None else orig_end

        # 유효성 검증: start < end, 최소 10초
        if final_start < final_end and (final_end - final_start) >= 10:
            h.start = _seconds_to_ts(final_start)
            h.end = _seconds_to_ts(final_end)
            log.info(
                "스냅 적용: %s→%s (원본 %s→%s)",
                h.start, h.end,
                _seconds_to_ts(orig_start), _seconds_to_ts(orig_end),
            )
        else:
            log.info("스냅 스킵 (유효하지 않음): 원본 유지 %s→%s", h.start, h.end)


async def run(ctx: PipelineContext, notify: Callable) -> None:
    ctx.update_progress(3, 0.1, "Gemini에 영상 업로드 중...")
    notify()

    raw_highlights = await analyze_highlights(
        video_path=ctx.source_path,
        clip_duration=ctx.clip_duration,
        clip_count=ctx.clip_count,
        video_duration=ctx.video_duration,
        transcript_segments=ctx.transcript_segments or None,
    )

    ctx.update_progress(3, 0.7, "하이라이트 분석 완료, 결과 정리 중...")
    notify()

    # Highlight 객체로 변환
    ctx.highlights = []
    for h in raw_highlights:
        line1 = h.get("title_line1", "")
        line2 = h.get("title_line2", "")
        # 기존 title 필드만 있는 경우 호환
        if not line1 and not line2 and h.get("title"):
            title = h["title"]
            mid = len(title) // 2
            line1 = title[:mid].strip()
            line2 = title[mid:].strip()
        title = f"{line1} {line2}".strip()

        ctx.highlights.append(Highlight(
            index=h.get("index", 0),
            title=title,
            title_line1=line1,
            title_line2=line2,
            summary=h.get("summary", ""),
            start=h.get("start", "00:00:00"),
            end=h.get("end", "00:00:00"),
            score=h.get("score", 50),
            reason=h.get("reason", ""),
        ))

    # 문장 경계 스냅
    if ctx.transcript_segments:
        ctx.update_progress(3, 0.85, "문장 경계에 맞춰 타임스탬프 보정 중...")
        notify()
        _snap_boundaries(ctx.highlights, ctx.transcript_segments)

    # score 내림차순 정렬
    ctx.highlights.sort(key=lambda x: x.score, reverse=True)

    # highlights.json 저장
    highlights_path = ctx.project_dir / "highlights.json"
    highlights_path.write_text(
        json.dumps([vars(h) for h in ctx.highlights], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ctx.update_progress(3, 1.0, f"{len(ctx.highlights)}개 하이라이트 발견")
    notify()
