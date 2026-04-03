"""Step 3: FFmpeg 클립 추출 — 하이라이트 구간별 정밀 컷."""
from __future__ import annotations

import asyncio
from typing import Callable

from pipeline.context import PipelineContext
from providers.ffmpeg import cut_clip


async def run(ctx: PipelineContext, notify: Callable) -> None:
    total = len(ctx.highlights)
    if total == 0:
        raise ValueError("추출할 하이라이트가 없습니다.")

    ctx.clip_paths = []
    loop = asyncio.get_event_loop()

    for i, h in enumerate(ctx.highlights):
        pct = i / total
        ctx.update_progress(4, pct, f"클립 {i+1}/{total} 추출 중...")
        notify()

        output = ctx.clips_dir / f"clip_{h.index:03d}.mp4"

        await loop.run_in_executor(
            None,
            cut_clip,
            ctx.source_path,
            output,
            h.start,
            h.end,
        )

        ctx.clip_paths.append(output)

    ctx.update_progress(4, 1.0, f"{total}개 클립 추출 완료")
    notify()
