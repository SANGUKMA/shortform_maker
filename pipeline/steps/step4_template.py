"""Step 4: FFmpeg 템플릿 적용 — 9:16 + 네이비 배경 + 제목/기관명."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from pipeline.context import PipelineContext
from providers.ffmpeg import apply_template

_log = logging.getLogger(__name__)


async def run(ctx: PipelineContext, notify: Callable) -> None:
    total = len(ctx.clip_paths)
    if total == 0:
        raise ValueError("템플릿을 적용할 클립이 없습니다.")

    ctx.short_paths = []
    loop = asyncio.get_event_loop()

    for i, (clip_path, highlight) in enumerate(zip(ctx.clip_paths, ctx.highlights)):
        pct = i / total
        ctx.update_progress(5, pct, f"템플릿 {i+1}/{total} 적용 중...")
        notify()

        output = ctx.shorts_dir / f"short_{highlight.index:03d}.mp4"

        # 최대 3회 재시도 (대용량 연속 인코딩 시 간헐적 실패 방지)
        last_err = None
        for attempt in range(1, 4):
            try:
                await loop.run_in_executor(
                    None,
                    lambda cp=clip_path, op=output, l1=highlight.title_line1, l2=highlight.title_line2, on=ctx.org_name, va=ctx.video_aspect:
                        apply_template(cp, op, l1, l2, on, video_aspect=va),
                )
                if attempt > 1:
                    _log.info("템플릿 %d/%d 재시도 성공 (시도 %d)", i+1, total, attempt)
                last_err = None
                break
            except Exception as e:
                last_err = e
                _log.warning("템플릿 %d/%d 실패 (시도 %d/%d): %s", i+1, total, attempt, 3, e)
                time.sleep(1)

        if last_err:
            raise last_err

        ctx.short_paths.append(output)

    ctx.update_progress(5, 1.0, f"{total}개 숏폼 생성 완료")
    notify()
