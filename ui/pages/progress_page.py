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

# 파이프라인 상태 추적 (중복 실행 방지 + 완료 감지)
_running: dict[str, bool] = {}
_completed: dict[str, bool] = {}


def register():
    @ui.page("/progress")
    def progress_page():
        state = app.storage.user

        source = state.get("source")
        if not source:
            ui.navigate.to("/")
            return

        # 이미 실행 중인 프로젝트가 있으면 중복 방지
        # 단, 같은 source로 새로 진입한 경우 이전 상태를 정리하고 재시작 허용
        existing_id = state.get("project_id")
        if existing_id and _running.get(existing_id):
            # 실제로 활성 태스크가 있는지 확인 — 없으면 좀비 상태이므로 정리
            _running.pop(existing_id, None)
            _completed.pop(existing_id, None)
            state.pop("project_id", None)

        ui.dark_mode(True)

        # 파이프라인 컨텍스트 생성
        ctx = PipelineContext(
            source=source,
            org_name=state.get("org_name", ""),
            clip_duration=state.get("clip_duration", "short"),
            clip_count=state.get("clip_count", "auto"),
            video_aspect=state.get("video_aspect", "16:9"),
            subtitle_enabled=state.get("subtitle_enabled", True),
        )
        state["project_id"] = ctx.project_id
        _running[ctx.project_id] = True
        _completed[ctx.project_id] = False

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
            if _completed.get(ctx.project_id):
                timer.deactivate()
                _running.pop(ctx.project_id, None)
                _completed.pop(ctx.project_id, None)
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
                _running.pop(ctx.project_id, None)
                _completed.pop(ctx.project_id, None)
                with error_area:
                    ui.label(f"오류: {ctx.error[:300]}").classes("text-red-400 text-center w-full")
                    ui.button(
                        "처음으로 돌아가기",
                        on_click=lambda: ui.navigate.to("/"),
                        icon="home",
                    ).classes("mx-auto")

        # 0.5초마다 UI 업데이트
        timer = ui.timer(0.5, update_ui)

        # 파이프라인을 백그라운드 태스크로 실행
        async def run_in_background():
            try:
                await run_pipeline(ctx, on_progress=lambda c: None)
                # 완료 플래그 설정 (타이머 콜백에서 감지하여 navigate 실행)
                _completed[ctx.project_id] = True
            except Exception as e:
                ctx.error = str(e)

        asyncio.create_task(run_in_background())
