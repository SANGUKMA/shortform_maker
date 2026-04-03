"""입력 페이지 — URL/파일 입력, 설정, 분석 시작."""
from __future__ import annotations

import logging
from pathlib import Path

from nicegui import app, ui

from config import OUTPUT_DIR

_log = logging.getLogger(__name__)


def register():
    @ui.page("/")
    def input_page():
        # 상태 저장소
        state = app.storage.user

        ui.dark_mode(True)

        with ui.column().classes("mx-auto max-w-2xl w-full p-8 gap-6"):
            # 헤더
            ui.label("ClipForge").classes("text-4xl font-bold text-center w-full")
            ui.label("롱폼 영상을 숏폼으로 자동 변환").classes(
                "text-lg text-gray-400 text-center w-full"
            )

            ui.separator()

            # YouTube URL 입력
            url_input = ui.input(
                label="YouTube URL",
                placeholder="https://www.youtube.com/watch?v=...",
            ).classes("w-full").props("outlined clearable")

            ui.label("또는").classes("text-center text-gray-500 w-full")

            # 파일 업로드
            file_path_holder = {"path": None}

            async def on_upload(e):
                try:
                    f = e.file  # NiceGUI 3.9 FileUpload object
                    _log.info("Upload event: name=%s, content_type=%s", f.name, f.content_type)
                    upload_dir = OUTPUT_DIR / "uploads"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    dest = upload_dir / f.name
                    data = await f.read()
                    dest.write_bytes(data)
                    file_path_holder["path"] = str(dest)
                    _log.info("Upload saved: %s (%d bytes)", dest, len(data))
                    ui.notify(f"파일 업로드 완료: {f.name} ({len(data)/1024/1024:.1f}MB)", type="positive")
                except Exception as ex:
                    import traceback
                    _log.error("Upload failed: %s\n%s", ex, traceback.format_exc())
                    ui.notify(f"업로드 실패: {ex}", type="negative")

            ui.upload(
                label="영상 파일 드래그 & 드롭",
                auto_upload=True,
                on_upload=on_upload,
            ).classes("w-full").props(
                'accept="video/*" max-file-size="5368709120" flat bordered'
            )

            ui.separator()

            # 설정
            with ui.card().classes("w-full p-4"):
                ui.label("설정").classes("text-lg font-bold mb-2")

                org_input = ui.input(
                    label="기관/채널명",
                    placeholder="예: 아이작TV",
                    value=state.get("org_name", ""),
                ).classes("w-full").props("outlined")

                with ui.row().classes("w-full gap-8 mt-2"):
                    with ui.column():
                        ui.label("클립 길이").classes("font-semibold")
                        duration_radio = ui.radio(
                            {"short": "쇼츠 (~60초)", "mid": "미드폼 (1~6분)"},
                            value="short",
                        )

                    with ui.column():
                        ui.label("클립 개수").classes("font-semibold")
                        count_select = ui.select(
                            {"auto": "자동 (AI 판단)", **{str(i): f"{i}개" for i in range(1, 11)}},
                            value="auto",
                        ).props("outlined dense")

                with ui.row().classes("w-full gap-8 mt-2"):
                    with ui.column():
                        ui.label("영상 비율").classes("font-semibold")
                        aspect_radio = ui.radio(
                            {"16:9": "16:9 (와이드)", "4:5": "4:5 (세로 확대, 줌인)"},
                            value="16:9",
                        )

                subtitle_toggle = ui.switch("자막 포함", value=True).classes("mt-2")

            # 분석 시작 버튼
            async def start_analysis():
                url_val = (url_input.value or "").strip()
                file_val = file_path_holder.get("path")

                if url_val:
                    source = url_val
                elif file_val:
                    source = file_val
                else:
                    ui.notify("YouTube URL을 입력하거나 영상 파일을 업로드하세요.", type="negative")
                    return

                if not (org_input.value or "").strip():
                    ui.notify("기관/채널명을 입력하세요.", type="negative")
                    return

                # 상태 저장
                count = count_select.value
                if count != "auto":
                    count = int(count)

                state["source"] = source
                state["org_name"] = org_input.value
                state["clip_duration"] = duration_radio.value
                state["clip_count"] = count
                state["video_aspect"] = aspect_radio.value
                state["subtitle_enabled"] = subtitle_toggle.value

                ui.navigate.to("/progress")

            ui.button(
                "분석 시작",
                on_click=start_analysis,
                icon="play_arrow",
            ).classes("w-full mt-4").props("size=lg color=primary")
