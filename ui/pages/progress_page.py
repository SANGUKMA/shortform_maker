"""진행 페이지 — 파이프라인을 백그라운드 태스크로 실행, 실시간 상태 표시."""
from __future__ import annotations

import asyncio

from nicegui import app, ui

from pipeline.context import PipelineContext
from pipeline.engine import run_pipeline

STEP_NAMES = [
    "영상 다운로드",
    "음성 전사",
    "AI 하이라이트 분석",
    "클립 추출",
    "템플릿 적용",
    "자막 생성",
    "출력 준비",
]

# 실행 중/완료된 파이프라인 (project_id → (ctx, task))
# 새로고침 시 같은 작업에 다시 연결하고, 태스크 참조를 유지해 GC로 사라지지 않게 한다.
_pipelines: dict[str, tuple[PipelineContext, asyncio.Task]] = {}


def _start_pipeline(state) -> tuple[PipelineContext, asyncio.Task]:
    """새 파이프라인을 백그라운드 태스크로 시작하고 등록한다."""
    # 끝난 작업은 정리 (결과 폴더도 새 실행 시작 시 삭제된다)
    for pid in [pid for pid, (_, t) in _pipelines.items() if t.done()]:
        del _pipelines[pid]

    ctx = PipelineContext(
        source=state["source"],
        org_name=state.get("org_name", ""),
        clip_duration=state.get("clip_duration", "short"),
        clip_count=state.get("clip_count", "auto"),
        video_aspect=state.get("video_aspect", "16:9"),
        subtitle_enabled=state.get("subtitle_enabled", True),
    )
    state["project_id"] = ctx.project_id

    async def run_in_background():
        try:
            await run_pipeline(ctx, on_progress=lambda c: None)
        except Exception as e:
            ctx.error = str(e)

    task = asyncio.create_task(run_in_background())
    _pipelines[ctx.project_id] = (ctx, task)
    return ctx, task


def register():
    @ui.page("/progress")
    def progress_page():
        state = app.storage.user

        source = state.get("source")
        if not source:
            ui.navigate.to("/")
            return

        existing = _pipelines.get(state.get("project_id"))

        if state.pop("start_new", False):
            # 입력 페이지에서 "분석 시작" — 이 사용자의 이전 작업은 중단 (폴더도 새 실행이 삭제함)
            if existing and not existing[1].done():
                existing[0].error = "새 작업이 시작되어 중단되었습니다."
                existing[1].cancel()
            ctx, task = _start_pipeline(state)
        elif existing:
            # 새로고침·뒤로가기 — 기존 작업에 다시 연결
            ctx, task = existing
        else:
            # 추적 중인 작업 없음 (서버 재시작 등) — 처음으로
            ui.navigate.to("/")
            return

        ui.dark_mode(True)

        with ui.column().classes("mx-auto max-w-2xl w-full p-8 gap-4"):
            ui.label("처리 진행 중...").classes("text-3xl font-bold text-center w-full")
            ui.separator()

            # 단계별 상태 표시
            step_labels = []
            step_icons = []
            for i, name in enumerate(STEP_NAMES):
                with ui.row().classes("w-full items-center gap-3"):
                    icon = ui.icon("radio_button_unchecked", color="gray").classes("text-xl")
                    label = ui.label(f"{i+1}. {name}").classes("text-base")
                    step_icons.append(icon)
                    step_labels.append(label)

            ui.separator()

            status_label = ui.label("준비 중...").classes("text-center text-gray-400 w-full")
            progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
            error_area = ui.column().classes("w-full")

        # UI 업데이트 함수 (타이머로 폴링 — UI 컨텍스트 안에서 실행됨)
        error_shown = False

        def update_ui():
            nonlocal error_shown
            progress_bar.set_value(ctx.overall_progress)
            status_label.set_text(ctx.status_message)

            for i in range(len(STEP_NAMES)):
                if i + 1 < ctx.current_step:
                    step_icons[i].props("name=check_circle color=green")
                    step_labels[i].classes(replace="text-green-400")
                elif i + 1 == ctx.current_step:
                    step_icons[i].props("name=sync color=blue")
                    step_labels[i].classes(replace="text-blue-400 font-bold")
                else:
                    step_icons[i].props("name=radio_button_unchecked color=gray")

            # 완료 감지 → 결과 페이지로 이동 (UI 컨텍스트 안이므로 navigate 작동)
            if task.done() and not ctx.error:
                timer.deactivate()
                # 모든 아이콘을 완료 상태로
                for icon in step_icons:
                    icon.props("name=check_circle color=green")
                for label in step_labels:
                    label.classes(replace="text-green-400")
                status_label.set_text("모든 처리 완료! 결과 페이지로 이동합니다...")
                progress_bar.set_value(1.0)
                ui.navigate.to(f"/result/{ctx.project_id}")

            # 에러 발생 시 (중복 방지)
            elif ctx.error and not error_shown:
                error_shown = True
                timer.deactivate()
                with error_area:
                    ui.label(f"오류: {ctx.error[:300]}").classes("text-red-400 text-center w-full")
                    ui.button(
                        "처음으로 돌아가기",
                        on_click=lambda: ui.navigate.to("/"),
                        icon="home",
                    ).classes("mx-auto")

        # 0.5초마다 UI 업데이트
        timer = ui.timer(0.5, update_ui)
