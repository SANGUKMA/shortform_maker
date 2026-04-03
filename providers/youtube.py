"""YouTube Data API v3 — OAuth 인증 및 영상 업로드."""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import settings

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def get_authenticated_service():
    """OAuth 인증 후 YouTube 서비스 객체 반환."""
    credentials = None
    token_path = Path(settings.YOUTUBE_TOKEN_PATH)

    if token_path.exists():
        with open(token_path, "rb") as f:
            credentials = pickle.load(f)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.YOUTUBE_CLIENT_SECRET, SCOPES
            )
            credentials = flow.run_local_server(port=8090)

        with open(token_path, "wb") as f:
            pickle.dump(credentials, f)

    return build("youtube", "v3", credentials=credentials)


def upload_video(
    file_path: str | Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "private",
    category_id: str = "22",
    on_progress: Any = None,
) -> str:
    """영상을 YouTube에 업로드하고 video_id를 반환한다."""
    youtube = get_authenticated_service()

    body: dict[str, Any] = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:30],
            "categoryId": category_id,
            "defaultLanguage": "ko",
            "defaultAudioLanguage": "ko",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(file_path),
        chunksize=10 * 1024 * 1024,
        resumable=True,
        mimetype="video/mp4",
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and on_progress:
            on_progress(status.progress())

    return response["id"]


def check_auth() -> bool:
    """YouTube 인증이 되어있는지 확인."""
    token_path = Path(settings.YOUTUBE_TOKEN_PATH)
    if not token_path.exists():
        return False
    try:
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            return True
    except Exception:
        return False
    return False
