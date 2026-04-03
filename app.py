"""ClipForge — 롱폼→숏폼 자동 변환 서비스 (NiceGUI 앱)."""
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from nicegui import app, ui

from config import OUTPUT_DIR
from ui.pages import input_page, progress_page, result_page, upload_page

# output 디렉토리 미디어 서빙 (앱 시작 시 1회 등록)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.add_media_files("/media", OUTPUT_DIR)

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
