"""클립 카드 컴포넌트 — 결과 페이지에서 각 클립을 표시."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui


def clip_card(
    index: int,
    title: str,
    summary: str,
    score: int,
    video_path: Path,
    file_size_mb: float,
    selected: set[int],
    on_title_change: callable = None,
) -> None:
    """클립 카드 하나를 렌더링한다."""

    with ui.card().classes("w-72 shadow-lg"):
        # 상단: 체크박스 + 점수
        with ui.row().classes("w-full items-center justify-between px-2 pt-2"):
            cb = ui.checkbox(
                f"#{index}",
                value=index in selected,
                on_change=lambda e, idx=index: _toggle(e, idx, selected),
            )
            score_color = "green" if score >= 80 else "orange" if score >= 60 else "red"
            ui.badge(f"{score}점", color=score_color).classes("text-sm")

        # 영상 미리보기
        if video_path.exists():
            ui.video(str(video_path)).classes("w-full rounded").props("controls")

        # 제목 (편집 가능)
        title_input = ui.input(
            value=title,
            label="제목",
        ).classes("w-full px-2").props("dense outlined")

        if on_title_change:
            title_input.on("blur", lambda e, idx=index: on_title_change(idx, title_input.value))

        # 요약
        ui.label(summary).classes("text-xs text-gray-500 px-2 pb-1 line-clamp-2")

        # 파일 크기
        ui.label(f"{file_size_mb} MB").classes("text-xs text-gray-400 px-2 pb-2")


def _toggle(event, index: int, selected: set[int]):
    if event.value:
        selected.add(index)
    else:
        selected.discard(index)
