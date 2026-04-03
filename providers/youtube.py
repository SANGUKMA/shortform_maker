"""YouTube Data API v3 — Web OAuth 인증 및 영상 업로드."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import settings

_log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _client_config() -> dict:
    """Google OAuth 웹 클라이언트 설정."""
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _redirect_uri() -> str:
    return f"{settings.APP_URL}/oauth/callback"


def get_auth_url() -> str:
    """Google OAuth2 인증 URL 생성."""
    flow = Flow.from_client_config(
        _client_config(), scopes=SCOPES, redirect_uri=_redirect_uri()
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url


def exchange_code(code: str) -> dict:
    """인증 코드를 토큰으로 교환, 직렬화 가능한 dict 반환."""
    flow = Flow.from_client_config(
        _client_config(), scopes=SCOPES, redirect_uri=_redirect_uri()
    )
    flow.fetch_token(code=code)
    return _creds_to_dict(flow.credentials)


def _creds_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }


def _dict_to_creds(d: dict) -> Credentials:
    return Credentials(
        token=d["token"],
        refresh_token=d.get("refresh_token"),
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d.get("client_id"),
        client_secret=d.get("client_secret"),
        scopes=d.get("scopes"),
    )


def check_auth(creds_dict: dict | None) -> bool:
    """저장된 credentials가 유효한지 확인."""
    if not creds_dict or "token" not in creds_dict:
        return False
    try:
        creds = _dict_to_creds(creds_dict)
        if creds.valid:
            return True
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            return True
    except Exception:
        return False
    return False


def upload_video(
    creds_dict: dict,
    file_path: str | Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "private",
    category_id: str = "22",
    on_progress: Any = None,
) -> tuple[str, dict]:
    """영상을 YouTube에 업로드하고 (video_id, updated_creds) 반환."""
    creds = _dict_to_creds(creds_dict)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    youtube = build("youtube", "v3", credentials=creds)

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

    return response["id"], _creds_to_dict(creds)
