"""ClipForge — 롱폼→숏폼 자동 변환 서비스 (NiceGUI 앱)."""
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from nicegui import app, ui

from ui.pages import input_page, progress_page, result_page, upload_page

# 페이지 등록
input_page.register()
progress_page.register()
result_page.register()
upload_page.register()

# 앱 실행
import os

ui.run(
    title="ClipForge - 롱폼을 숏폼으로",
    host="0.0.0.0",
    port=int(os.getenv("PORT", 8080)),
    reload=False,
    storage_secret=os.getenv("STORAGE_SECRET", "clipforge-secret-key-change-me"),
    dark=True,
)
