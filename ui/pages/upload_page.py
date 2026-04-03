"""업로드 페이지 — YouTube 업로드 설정 및 실행."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nicegui import app, ui

from config import OUTPUT_DIR
from providers.youtube import check_auth, get_auth_url, upload_video


def register():
    @ui.page("/upload/{project_id}")
    async def upload_page(project_id: str):
        ui.dark_mode(True)
        state = app.storage.user

        project_dir = OUTPUT_DIR / project_id
        meta_path = project_dir / "metadata.json"

        if not meta_path.exists():
            ui.label("프로젝트를 찾을 수 없습니다.").classes("text-red-400")
            return

        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        all_clips = metadata.get("clips", [])
        selected_indices = set(state.get("upload_selected", []))
        saved_titles = state.get("upload_titles", {})

        # 선택된 클립만 필터
        clips = [c for c in all_clips if c["index"] in selected_indices]

        if not clips:
            ui.label("업로드할 클립이 없습니다.").classes("text-center")
            ui.button("돌아가기", on_click=lambda: ui.navigate.to(f"/result/{project_id}"))
            return

        with ui.column().classes("mx-auto max-w-3xl w-full p-6 gap-4"):
            ui.label("YouTube 업로드 설정").classes("text-3xl font-bold text-center w-full")

            # 인증 상태 확인
            creds = state.get("youtube_creds")
            is_authed = check_auth(creds)
            if not is_authed:
                with ui.card().classes("w-full p-4 bg-yellow-900"):
                    ui.label("YouTube 인증이 필요합니다.").classes("font-bold")
                    ui.label("아래 버튼을 클릭하면 Google 로그인 페이지로 이동합니다.")

                    def do_auth():
                        state["oauth_return_to"] = f"/upload/{project_id}"
                        auth_url = get_auth_url()
                        ui.navigate.to(auth_url, new_tab=False)

                    ui.button("YouTube 인증", on_click=do_auth, icon="login").props(
                        "color=red"
                    )
                return

            ui.separator()

            # 공통 설정
            with ui.card().classes("w-full p-4"):
                ui.label("공통 설정").classes("font-bold mb-2")
                privacy_select = ui.select(
                    {"private": "비공개", "unlisted": "미등록", "public": "공개"},
                    value="private",
                    label="공개 설정",
                ).props("outlined dense")

            ui.separator()

            # 클립별 설정
            clip_settings: dict[int, dict] = {}

            for clip in clips:
                idx = clip["index"]
                title = saved_titles.get(str(idx), saved_titles.get(idx, clip["title"]))
                desc = clip.get("description", clip.get("summary", ""))
                tags = clip.get("tags", [])
                tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)

                with ui.card().classes("w-full p-4"):
                    ui.label(f"클립 #{idx}").classes("font-bold text-lg")

                    t_input = ui.input(
                        label="제목",
                        value=title,
                    ).classes("w-full").props("outlined")

                    d_input = ui.textarea(
                        label="설명",
                        value=desc,
                    ).classes("w-full").props("outlined rows=5")

                    tag_input = ui.input(
                        label="태그 (쉼표 구분)",
                        value=tags_str,
                    ).classes("w-full").props("outlined")

                    clip_settings[idx] = {
                        "title": t_input,
                        "description": d_input,
                        "tags": tag_input,
                        "file": clip["file"],
                    }

            ui.separator()

            # 업로드 상태 — 라벨을 미리 생성하고 텍스트만 갱신 (DOM 비대화 방지)
            status_area = ui.column().classes("w-full gap-2")
            with status_area:
                status_header = ui.label("").classes("text-blue-400")
                status_header.set_visibility(False)
                status_labels: dict[int, ui.label] = {}
                for idx in clip_settings:
                    lbl = ui.label(f"클립 #{idx} 대기 중").classes("text-gray-400")
                    status_labels[idx] = lbl
                status_footer = ui.label("").classes("text-green-400 font-bold text-lg")
                status_footer.set_visibility(False)
                home_btn = ui.button(
                    "처음으로",
                    on_click=lambda: ui.navigate.to("/"),
                    icon="home",
                )
                home_btn.set_visibility(False)

            async def do_upload():
                status_header.set_text("업로드 시작...")
                status_header.set_visibility(True)

                user_creds = state.get("youtube_creds")

                for idx, s in clip_settings.items():
                    file_path = project_dir / "final" / s["file"]
                    if not file_path.exists():
                        file_path = project_dir / "shorts" / s["file"].replace("final_", "short_")

                    title = s["title"].value
                    desc = s["description"].value
                    tags = [t.strip() for t in s["tags"].value.split(",") if t.strip()]
                    privacy = privacy_select.value

                    lbl = status_labels[idx]
                    lbl.set_text(f"클립 #{idx} '{title}' 업로드 중...")
                    lbl.classes(replace="text-blue-400")

                    try:
                        loop = asyncio.get_event_loop()
                        video_id, updated_creds = await loop.run_in_executor(
                            None,
                            lambda: upload_video(
                                creds_dict=user_creds,
                                file_path=file_path,
                                title=title,
                                description=desc,
                                tags=tags,
                                privacy=privacy,
                            ),
                        )
                        # 갱신된 토큰 저장
                        user_creds = updated_creds
                        state["youtube_creds"] = updated_creds

                        lbl.set_text(f"클립 #{idx} 업로드 완료! ID: {video_id}")
                        lbl.classes(replace="text-green-400")
                    except Exception as e:
                        lbl.set_text(f"클립 #{idx} 업로드 실패: {e}")
                        lbl.classes(replace="text-red-400")

                status_footer.set_text("모든 업로드 완료!")
                status_footer.set_visibility(True)
                home_btn.set_visibility(True)

            with ui.row().classes("w-full justify-center gap-4"):
                ui.button(
                    "업로드 실행",
                    on_click=do_upload,
                    icon="cloud_upload",
                ).props("color=red size=lg")

                ui.button(
                    "돌아가기",
                    on_click=lambda: ui.navigate.to(f"/result/{project_id}"),
                    icon="arrow_back",
                ).props("size=lg outline")

    @ui.page("/oauth/callback")
    async def oauth_callback():
        """Google OAuth 콜백 — 인증 코드를 토큰으로 교환 후 리다이렉트."""
        ui.dark_mode(True)
        with ui.column().classes("mx-auto max-w-md w-full p-8 gap-4 items-center"):
            spinner = ui.spinner("dots", size="xl")
            status = ui.label("YouTube 인증 처리 중...").classes("text-center text-lg")

        async def process_code():
            from providers.youtube import exchange_code

            code = await ui.run_javascript(
                "new URLSearchParams(window.location.search).get('code')"
            )
            if not code:
                spinner.set_visibility(False)
                status.set_text("인증 코드를 받지 못했습니다.")
                status.classes(add="text-red-400")
                return

            try:
                loop = asyncio.get_event_loop()
                creds_dict = await loop.run_in_executor(None, exchange_code, code)
                app.storage.user["youtube_creds"] = creds_dict

                status.set_text("인증 완료! 리다이렉트 중...")
                status.classes(add="text-green-400")

                return_to = app.storage.user.get("oauth_return_to", "/")
                ui.navigate.to(return_to)
            except Exception as e:
                spinner.set_visibility(False)
                status.set_text(f"인증 실패: {e}")
                status.classes(add="text-red-400")

        ui.timer(0.5, process_code, once=True)
