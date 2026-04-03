"""결과 페이지 — 생성된 클립 미리보기 및 선택."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from nicegui import app, ui

from config import OUTPUT_DIR


def register():
    @ui.page("/result/{project_id}")
    def result_page(project_id: str):
        ui.dark_mode(True)
        state = app.storage.user

        project_dir = OUTPUT_DIR / project_id
        meta_path = project_dir / "metadata.json"

        if not meta_path.exists():
            ui.label("프로젝트를 찾을 수 없습니다.").classes("text-center text-red-400")
            ui.button("처음으로", on_click=lambda: ui.navigate.to("/"))
            return

        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        clips = metadata.get("clips", [])

        # 선택 상태
        selected: set[int] = set()
        # 수정된 제목 저장
        titles: dict[int, str] = {c["index"]: c["title"] for c in clips}

        with ui.column().classes("mx-auto max-w-6xl w-full p-6 gap-4"):
            # 헤더
            ui.label("생성 완료!").classes("text-3xl font-bold text-center w-full")
            ui.label(
                f'원본: "{metadata.get("video_title", "")}" → {len(clips)}개 클립'
            ).classes("text-gray-400 text-center w-full")

            ui.separator()

            # 클립 카드 그리드
            with ui.row().classes("w-full flex-wrap gap-4 justify-center"):
                for clip in clips:
                    idx = clip["index"]
                    video_file = project_dir / "final" / clip["file"]
                    if not video_file.exists():
                        video_file = project_dir / "shorts" / clip["file"].replace("final_", "short_")

                    with ui.card().classes("w-72 shadow-lg"):
                        # 체크박스 + 점수
                        with ui.row().classes("w-full items-center justify-between px-2 pt-2"):
                            ui.checkbox(
                                f"#{idx}",
                                value=False,
                                on_change=lambda e, i=idx: (
                                    selected.add(i) if e.value else selected.discard(i)
                                ),
                            )
                            score = clip.get("score", 0)
                            sc = "green" if score >= 80 else "orange" if score >= 60 else "red"
                            ui.badge(f"{score}점", color=sc)

                        # 영상 미리보기
                        if video_file.exists():
                            subdir = "final" if "final" in str(video_file.parent) else "shorts"
                            ui.video(
                                f"/media/{project_id}/{subdir}/{video_file.name}"
                            ).classes("w-full").props("controls")

                        # 제목 편집
                        ui.input(
                            value=clip["title"],
                            label="제목",
                            on_change=lambda e, i=idx: titles.update({i: e.value}),
                        ).classes("w-full px-2").props("dense outlined")

                        # 요약 + 크기
                        ui.label(clip.get("summary", "")).classes(
                            "text-xs text-gray-500 px-2 line-clamp-2"
                        )
                        ui.label(f'{clip.get("file_size_mb", 0)} MB').classes(
                            "text-xs text-gray-400 px-2 pb-2"
                        )

            ui.separator()

            # 하단 액션 버튼
            with ui.row().classes("w-full justify-center gap-4"):
                ui.button(
                    "YouTube 업로드",
                    on_click=lambda: _go_upload(project_id, selected, titles, state),
                    icon="upload",
                ).props("color=red size=lg")

                ui.button(
                    "전체 다운로드 (ZIP)",
                    on_click=lambda: _download_all(project_id, clips, project_dir),
                    icon="download",
                ).props("color=primary size=lg outline")

                ui.button(
                    "선택 다운로드",
                    on_click=lambda: _download_selected(project_id, selected, clips, project_dir),
                    icon="download",
                ).props("color=primary size=lg outline")

            ui.separator()

            ui.button(
                "새 영상 변환",
                on_click=lambda: ui.navigate.to("/"),
                icon="add",
            ).classes("mx-auto")


def _go_upload(project_id: str, selected: set, titles: dict, state):
    if not selected:
        ui.notify("업로드할 클립을 선택하세요.", type="warning")
        return
    state["upload_selected"] = list(selected)
    state["upload_titles"] = titles
    ui.navigate.to(f"/upload/{project_id}")


def _download_all(project_id: str, clips: list, project_dir: Path):
    zip_path = project_dir / f"{project_id}_all.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for clip in clips:
            fp = project_dir / "final" / clip["file"]
            if not fp.exists():
                fp = project_dir / "shorts" / clip["file"].replace("final_", "short_")
            if fp.exists():
                zf.write(fp, clip["file"])
    ui.download(f"/media/{project_id}/{zip_path.name}")


def _download_selected(project_id: str, selected: set, clips: list, project_dir: Path):
    if not selected:
        ui.notify("다운로드할 클립을 선택하세요.", type="warning")
        return
    zip_path = project_dir / f"{project_id}_selected.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for clip in clips:
            if clip["index"] in selected:
                fp = project_dir / "final" / clip["file"]
                if not fp.exists():
                    fp = project_dir / "shorts" / clip["file"].replace("final_", "short_")
                if fp.exists():
                    zf.write(fp, clip["file"])
    ui.download(f"/media/{project_id}/{zip_path.name}")
