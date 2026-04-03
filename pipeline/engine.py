from __future__ import annotations

import asyncio
import logging
import shutil
import traceback
from typing import Callable

from pipeline.context import PipelineContext

_log = logging.getLogger(__name__)
from pipeline.steps.step1_download import run as step1
from pipeline.steps.step1b_transcribe import run as step1b
from pipeline.steps.step2_analyze import run as step2
from pipeline.steps.step3_extract import run as step3
from pipeline.steps.step4_template import run as step4
from pipeline.steps.step5_subtitle import run as step5
from pipeline.steps.step6_output import run as step6

STEPS = [
    (1, "영상 다운로드", step1),
    (2, "음성 전사", step1b),
    (3, "AI 하이라이트 분석", step2),
    (4, "클립 추출", step3),
    (5, "템플릿 적용", step4),
    (6, "자막 생성", step5),
    (7, "출력 준비", step6),
]


async def run_pipeline(
    ctx: PipelineContext,
    on_progress: Callable[[PipelineContext], None] | None = None,
) -> PipelineContext:
    """파이프라인 전체 실행."""

    def _notify():
        if on_progress:
            on_progress(ctx)

    for step_num, name, step_fn in STEPS:
        # 자막 비활성화 시 step6 건너뛰기
        if step_num == 6 and not ctx.subtitle_enabled:
            ctx.final_paths = list(ctx.short_paths)
            continue

        ctx.update_progress(step_num, 0.0, f"{name} 시작...")
        _notify()

        try:
            await step_fn(ctx, _notify)
        except Exception as e:
            ctx.error = f"Step {step_num} ({name}) 실패: {e}\n{traceback.format_exc()}"
            ctx.status_message = f"오류: {name} 실패"
            _notify()
            raise

        ctx.update_progress(step_num, 1.0, f"{name} 완료")
        _notify()

    # 중간 산출물 정리 (source.mp4, full_audio.wav, clips/, shorts/)
    _cleanup_intermediates(ctx)

    ctx.status_message = "모든 처리 완료!"
    _notify()
    return ctx


def _cleanup_intermediates(ctx: PipelineContext) -> None:
    """파이프라인 완료 후 중간 산출물을 삭제하여 디스크 절약.

    보존: final/, metadata.json, highlights.json, transcript.json, *.srt
    삭제: source.mp4, full_audio.wav, clips/, shorts/
    """
    project_dir = ctx.project_dir
    saved = 0

    # 대용량 파일 삭제
    for fname in ("source.mp4", "full_audio.wav"):
        f = project_dir / fname
        if f.exists():
            size = f.stat().st_size
            f.unlink()
            saved += size
            _log.info("정리: %s 삭제 (%.1fMB)", fname, size / 1024 / 1024)

    # 중간 디렉토리 삭제
    for dname in ("clips", "shorts"):
        d = project_dir / dname
        if d.exists():
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            shutil.rmtree(d)
            saved += size
            _log.info("정리: %s/ 삭제 (%.1fMB)", dname, size / 1024 / 1024)

    if saved > 0:
        _log.info("총 %.1fMB 디스크 절약", saved / 1024 / 1024)
