"""YouTube Data API v3 — Web OAuth 인증 및 영상 업로드."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import settings

_log = logging.getLogger(__name__)

# Google이 돌려준 권한 목록이 요청과 달라도(동의 화면에서 일부 해제, 이전에 허용한 권한 포함)
# oauthlib가 예외로 멈추지 않게 한다. 업로드 권한은 exchange_code에서 직접 확인한다.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
SCOPES = [
    UPLOAD_SCOPE,
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


def get_auth_url() -> tuple[str, str, str]:
    """Google OAuth2 인증 URL 생성.

    Returns: (auth_url, state, code_verifier).
    인증 URL에는 code_verifier에서 만든 PKCE 확인값이 붙으므로, state와 code_verifier를
    사용자 세션에 보관했다가 콜백에서 exchange_code에 넘겨야 한다.
    """
    flow = Flow.from_client_config(
        _client_config(), scopes=SCOPES, redirect_uri=_redirect_uri()
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url, state, flow.code_verifier


def exchange_code(code: str, code_verifier: str) -> dict:
    """인증 코드를 토큰으로 교환, 직렬화 가능한 dict 반환.

    code_verifier는 get_auth_url이 돌려준 값이어야 한다 (없으면 Google이 invalid_grant로 거부).
    """
    flow = Flow.from_client_config(
        _client_config(), scopes=SCOPES, redirect_uri=_redirect_uri(),
        code_verifier=code_verifier, autogenerate_code_verifier=False,
    )
    flow.fetch_token(code=code)

    granted = flow.oauth2session.token.get("scope") or SCOPES
    if isinstance(granted, str):
        granted = granted.split()
    if UPLOAD_SCOPE not in granted:
        raise PermissionError(
            "YouTube 업로드 권한이 허용되지 않았습니다. "
            "다시 인증하면서 Google 동의 화면의 YouTube 권한을 모두 체크해 주세요."
        )
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
