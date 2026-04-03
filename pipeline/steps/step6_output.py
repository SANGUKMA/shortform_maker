"""Step 6: 출력 준비 — 최종 파일 확인, YouTube 메타데이터 자동 생성, 저장."""
from __future__ import annotations

import json
import logging
from typing import Callable

from pipeline.context import PipelineContext
from providers.gemini import generate_metadata

_log = logging.getLogger(__name__)


async def run(ctx: PipelineContext, notify: Callable) -> None:
    ctx.update_progress(7, 0.2, "최종 파일 확인 중...")
    notify()

    # 최종 파일 경로 결정 (자막 OFF 시 short_paths가 final)
    if not ctx.final_paths:
        ctx.final_paths = list(ctx.short_paths)

    # 기본 클립 정보 수집
    clips_info = []
    for i, (final_path, highlight) in enumerate(zip(ctx.final_paths, ctx.highlights)):
        if not final_path.exists():
            continue
        clips_info.append({
            "index": i + 1,
            "title": highlight.title,
            "title_line1": highlight.title_line1,
            "title_line2": highlight.title_line2,
            "summary": highlight.summary,
            "score": highlight.score,
            "file": str(final_path.name),
            "file_size_mb": round(final_path.stat().st_size / (1024 * 1024), 1),
        })

    # Gemini로 YouTube 설명/태그 자동 생성
    ctx.update_progress(7, 0.4, "YouTube 메타데이터 생성 중...")
    notify()

    try:
        meta_list = await generate_metadata(
            video_title=ctx.video_title,
            org_name=ctx.org_name,
            clips=clips_info,
        )
        # 생성된 메타데이터를 클립 정보에 병합
        meta_by_idx = {m["index"]: m for m in meta_list}
        for clip in clips_info:
            m = meta_by_idx.get(clip["index"], {})
            clip["description"] = m.get("description", clip["summary"])
            clip["tags"] = m.get("tags", [])
    except Exception as e:
        _log.warning("메타데이터 자동 생성 실패 (기본값 사용): %s", e)
        for clip in clips_info:
            clip["description"] = clip["summary"]
            clip["tags"] = []

    # 메타데이터 JSON 저장
    metadata = {
        "project_id": ctx.project_id,
        "source": ctx.source,
        "video_title": ctx.video_title,
        "video_duration": ctx.video_duration,
        "org_name": ctx.org_name,
        "clip_duration": ctx.clip_duration,
        "subtitle_enabled": ctx.subtitle_enabled,
        "clips": clips_info,
    }

    meta_path = ctx.project_dir / "metadata.json"
    meta_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ctx.update_progress(7, 1.0, f"총 {len(ctx.final_paths)}개 클립 준비 완료")
    notify()
