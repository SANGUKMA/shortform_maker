"""Step 2: Claude 하이라이트 선택 — 문장 번호 범위를 Whisper 세그먼트 시각으로 변환."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from config import settings
from pipeline.context import Highlight, PipelineContext
from providers.claude import select_highlights

log = logging.getLogger(__name__)

# 클립 길이 허용 범위(초). 프롬프트 기준(30~60초 / 1~6분)보다 약간 넓게 둔다.
DURATION_LIMITS = {"short": (20.0, 75.0), "mid": (50.0, 400.0)}

# 클립 안에서 이웃 문장 사이가 이보다 벌어지면 음악·무음을 빼고 이어 붙인 자리로 본다.
# Whisper 문장은 보통 끝과 다음 시작이 붙어 있다.
MAX_GAP = 5.0


def _seconds_to_ts(sec: float) -> str:
    """seconds → HH:MM:SS.mmm (FFmpeg -ss 형식)."""
    ms = round(max(0.0, sec) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _refine_bounds(ctx: PipelineContext, ranges: list[tuple[int, int]]) -> None:
    """wav2vec2 정렬로 각 클립의 시작·끝을 실제 첫/마지막 음절 기준으로 보정한다."""
    # numpy·torch는 로컬 전용 의존성이라 켜져 있을 때만 불러온다 (Railway에는 없음)
    from providers import aligner

    audio = aligner.load_audio(ctx.full_audio_path)
    segments = ctx.transcript_segments
    for h, (s, e) in zip(ctx.highlights, ranges):
        _, start = aligner.refine_boundary(audio, segments, s - 1)
        end, _ = aligner.refine_boundary(audio, segments, e)
        if start is not None:
            log.info("클립 #%d 시작 보정: %s → %s", h.index, h.start, _seconds_to_ts(start))
            h.start = _seconds_to_ts(start)
        if end is not None:
            log.info("클립 #%d 끝 보정: %s → %s", h.index, h.end, _seconds_to_ts(end))
            h.end = _seconds_to_ts(end)


async def run(ctx: PipelineContext, notify: Callable) -> None:
    segments = ctx.transcript_segments
    if not segments:
        raise ValueError("말소리로 인식된 문장이 없습니다. 음악·무음만 있는 영상일 수 있습니다.")

    ctx.update_progress(3, 0.1, f"Claude가 {len(segments)}개 문장에서 하이라이트 선택 중...")
    notify()

    picks = await select_highlights(
        segments=segments,
        clip_duration=ctx.clip_duration,
        clip_count=ctx.clip_count,
        video_title=ctx.video_title,
        org_name=ctx.org_name,
    )

    ctx.update_progress(3, 0.8, "선택 구간 검증 중...")
    notify()

    min_dur, max_dur = DURATION_LIMITS.get(ctx.clip_duration, DURATION_LIMITS["short"])
    used: set[int] = set()
    highlights: list[Highlight] = []
    ranges: list[tuple[int, int]] = []   # 채택된 클립의 (start_seg, end_seg) — 경계 보정용

    # 점수 높은 순으로 검증해, 겹치면 낮은 쪽을 버린다
    for p in sorted(picks, key=lambda x: x.score, reverse=True):
        if p.score < settings.CLAUDE_MIN_SCORE:
            log.warning("점수 %d점 클립 버림: %d~%d", p.score, p.start_seg, p.end_seg)
            continue

        if not (0 <= p.start_seg <= p.end_seg < len(segments)):
            log.warning("범위 밖 문장 번호 버림: %d~%d", p.start_seg, p.end_seg)
            continue

        start = segments[p.start_seg]["start"]
        end = segments[p.end_seg]["end"]
        if not (min_dur <= end - start <= max_dur):
            log.warning("길이 %.1f초 클립 버림: %d~%d", end - start, p.start_seg, p.end_seg)
            continue

        gaps = [
            segments[i + 1]["start"] - segments[i]["end"]
            for i in range(p.start_seg, p.end_seg)
        ]
        if gaps and max(gaps) > MAX_GAP:
            log.warning("%.1f초 빈 구간을 걸친 클립 버림: %d~%d", max(gaps), p.start_seg, p.end_seg)
            continue

        seg_range = set(range(p.start_seg, p.end_seg + 1))
        if seg_range & used:
            log.warning("다른 클립과 겹쳐 버림: %d~%d", p.start_seg, p.end_seg)
            continue
        used |= seg_range

        highlights.append(Highlight(
            index=len(highlights) + 1,
            title=f"{p.title_line1} {p.title_line2}".strip(),
            title_line1=p.title_line1,
            title_line2=p.title_line2,
            summary=p.summary,
            start=_seconds_to_ts(start),
            end=_seconds_to_ts(end),
            score=p.score,
            reason=p.reason,
            description=p.description,
            tags=p.tags,
        ))
        ranges.append((p.start_seg, p.end_seg))

    if not picks:
        raise RuntimeError("Claude가 쇼츠로 쓸 만한 구간을 찾지 못했습니다.")
    if not highlights:
        raise RuntimeError(f"Claude가 고른 {len(picks)}개 구간이 모두 검증에 실패했습니다.")
    if len(highlights) < len(picks):
        log.info("하이라이트 %d개 중 %d개 채택", len(picks), len(highlights))

    ctx.highlights = highlights

    # 경계 보정 (로컬 전용 선택 기능) — 실패해도 Whisper 시각으로 계속 진행
    if settings.ALIGN_ENABLED and ctx.full_audio_path:
        ctx.update_progress(3, 0.9, "문장 경계 정밀 보정 중 (wav2vec2)...")
        notify()
        try:
            await asyncio.get_event_loop().run_in_executor(None, _refine_bounds, ctx, ranges)
        except Exception as e:
            log.warning("경계 보정 실패, Whisper 시각 사용: %s", e)

    # highlights.json 저장
    highlights_path = ctx.project_dir / "highlights.json"
    highlights_path.write_text(
        json.dumps([vars(h) for h in ctx.highlights], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ctx.update_progress(3, 1.0, f"{len(ctx.highlights)}개 하이라이트 발견")
    notify()
