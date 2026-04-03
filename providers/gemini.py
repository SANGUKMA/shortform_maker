"""Gemini 2.5 Flash — 영상 하이라이트 분석 (google-genai SDK)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from google import genai
from google.genai import types

from config import settings

_log = logging.getLogger(__name__)


def _build_prompt(
    clip_duration: str,
    clip_count: int | str,
    video_duration: int = 0,
    transcript_segments: list[dict] | None = None,
) -> str:
    if clip_duration == "short":
        length_guide = "각 클립은 30~60초 이내"
    else:
        length_guide = "각 클립은 1~6분 사이"

    if isinstance(clip_count, int):
        count_guide = f"정확히 {clip_count}개의 클립을 추출하세요."
    else:
        count_guide = "적절한 개수의 클립을 추출하세요 (최소 3개, 최대 10개)."

    dur_min = video_duration // 60
    dur_sec = video_duration % 60
    dur_info = f"이 영상의 총 길이는 약 {dur_min}분 {dur_sec}초입니다." if video_duration > 0 else ""

    # 전사본을 타임스탬프와 함께 포맷
    transcript_section = ""
    if transcript_segments:
        lines = []
        for s in transcript_segments:
            mm = int(s["start"]) // 60
            ss = int(s["start"]) % 60
            lines.append(f"[{mm:02d}:{ss:02d}] {s['text']}")
        transcript_text = "\n".join(lines)
        transcript_section = f"""
아래는 이 영상의 음성 전사본입니다 (타임스탬프 포함).
클립의 시작과 끝을 정할 때 반드시 이 전사본을 참고하여, 문장이 완결되는 지점에서 끊으세요.

전사본:
{transcript_text}
"""

    return f"""이 영상을 분석하여 숏폼 콘텐츠로 만들기에 가장 적합한 하이라이트 구간을 추출하세요.

{dur_info}
{transcript_section}
요구사항:
- {length_guide}
- {count_guide}
- 각 클립은 독립적으로 이해 가능해야 합니다
- 시청자의 관심을 끌 수 있는 흥미로운 구간을 우선 선택하세요
- **중요: 클립의 시작은 문장이 시작되는 지점, 끝은 문장이 완전히 끝나는 지점이어야 합니다**
- **말이 중간에 끊기면 안 됩니다. 화자의 발화가 자연스럽게 마무리된 후 끊으세요**

반드시 아래 JSON 형식으로만 응답하세요. 마크다운 코드블록 없이 순수 JSON만 출력하세요:
[
  {{
    "index": 1,
    "title_line1": "첫줄 (8자 이내)",
    "title_line2": "둘째줄 (8자 이내)",
    "summary": "20자 이내 요약",
    "start": "MM:SS",
    "end": "MM:SS",
    "score": 92,
    "reason": "20자 이내 이유"
  }}
]

제목 규칙:
- title_line1: 핵심 키워드 (8자 이내, 예: "충격 발언!")
- title_line2: 부연 설명 (8자 이내, 예: "군중의 변심")
- 두 줄이 합쳐서 하나의 의미를 전달해야 합니다

타임스탬프 규칙:
- MM:SS 형식 (예: 01:30은 1분30초, 05:08은 5분8초)
- 반드시 영상 길이({dur_min}분{dur_sec}초) 범위 안의 시간이어야 합니다
- score는 0~100, 내림차순 정렬"""


async def analyze_highlights(
    video_path: Path,
    clip_duration: str = "short",
    clip_count: int | str = "auto",
    video_duration: int = 0,
    transcript_segments: list[dict] | None = None,
) -> list[dict]:
    """Gemini로 영상을 분석하여 하이라이트 구간을 추출한다."""
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # 영상 업로드
    loop = asyncio.get_event_loop()
    video_file = await loop.run_in_executor(
        None,
        lambda: client.files.upload(file=str(video_path)),
    )

    # 업로드 처리 대기
    while video_file.state == "PROCESSING":
        await asyncio.sleep(3)
        video_file = await loop.run_in_executor(
            None,
            lambda: client.files.get(name=video_file.name),
        )

    if video_file.state == "FAILED":
        raise RuntimeError(f"Gemini 영상 업로드 실패: {video_file.state}")

    # 분석 요청 (최대 5회 재시도, 503 시 fallback 모델 사용)
    prompt = _build_prompt(clip_duration, clip_count, video_duration, transcript_segments)
    models_to_try = [settings.GEMINI_MODEL, "gemini-2.5-flash-lite"]
    max_retries = 5
    response = None

    for attempt in range(1, max_retries + 1):
        # 3회 이상 실패 시 fallback 모델로 전환
        current_model = models_to_try[0] if attempt <= 3 else models_to_try[-1]
        try:
            response = await loop.run_in_executor(
                None,
                lambda m=current_model: client.models.generate_content(
                    model=m,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part.from_uri(
                                    file_uri=video_file.uri,
                                    mime_type=video_file.mime_type,
                                ),
                                types.Part.from_text(text=prompt),
                            ]
                        )
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=16384,
                    ),
                ),
            )
            break
        except Exception as e:
            _log.warning("Gemini 분석 실패 (모델=%s, 시도 %d/%d): %s", current_model, attempt, max_retries, e)
            if attempt == max_retries:
                raise
            await asyncio.sleep(5 * attempt)

    # 응답 텍스트 추출
    text = ""
    try:
        text = response.text or ""
    except (ValueError, AttributeError):
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text

    text = text.strip()
    if not text:
        raise RuntimeError(
            f"Gemini 응답이 비어있습니다. "
            f"finish_reason: {getattr(response.candidates[0], 'finish_reason', 'unknown') if response.candidates else 'no candidates'}"
        )

    # [ 부터 시작하는 JSON 배열 추출 (마크다운/기타 텍스트 무시)
    bracket_pos = text.find("[")
    if bracket_pos == -1:
        raise RuntimeError(f"Gemini 응답에 JSON 배열이 없습니다.\n응답: {text[:300]}")
    text = text[bracket_pos:]

    # 뒤쪽 ``` 등 제거
    last_bracket = text.rfind("]")
    if last_bracket > 0:
        text = text[:last_bracket + 1]

    # 잘린 JSON 복구: ] 가 없으면 마지막 } 뒤에서 닫기
    try:
        highlights = json.loads(text)
    except json.JSONDecodeError:
        last_brace = text.rfind("}")
        if last_brace > 0:
            text = text[:last_brace + 1] + "]"
            try:
                highlights = json.loads(text)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Gemini JSON 파싱 실패: {e}\n응답: {text[:300]}")
        else:
            raise RuntimeError(f"Gemini JSON 복구 실패\n응답: {text[:300]}")

    # 타임스탬프 정규화: MM:SS → 00:MM:SS
    for h in highlights:
        h["start"] = _normalize_timestamp(h.get("start", "00:00:00"))
        h["end"] = _normalize_timestamp(h.get("end", "00:00:00"))

    # 업로드된 파일 정리
    try:
        await loop.run_in_executor(
            None,
            lambda: client.files.delete(name=video_file.name),
        )
    except Exception:
        pass

    return highlights


async def generate_metadata(
    video_title: str,
    org_name: str,
    clips: list[dict],
) -> list[dict]:
    """각 클립에 대한 YouTube 설명과 태그를 생성한다."""
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    clips_info = "\n".join(
        f"- 클립 {c['index']}: 제목=\"{c['title']}\", 요약=\"{c['summary']}\""
        for c in clips
    )

    prompt = f"""아래 영상에서 추출한 숏폼 클립들의 YouTube 업로드용 메타데이터를 생성하세요.

원본 영상: "{video_title}"
채널명: "{org_name}"

클립 목록:
{clips_info}

각 클립에 대해 아래 JSON 배열 형식으로 응답하세요. 마크다운 없이 순수 JSON만:
[
  {{
    "index": 1,
    "description": "YouTube Shorts 설명 (3~5줄, 핵심 내용 요약 + 원본 영상 안내 + 채널 구독 유도, 해시태그 3~5개 포함)",
    "tags": ["태그1", "태그2", "태그3", "...최대 10개"]
  }}
]

규칙:
- description은 한국어, 자연스럽고 간결하게
- 첫 줄은 클립 핵심 내용을 한 문장으로
- 마지막에 해시태그 (#숏츠 #Shorts 포함, 주제 관련 3~5개)
- tags는 검색 최적화용 키워드 (한국어+영어 혼합, 최대 10개)
- 원본 영상 채널({org_name}) 언급"""

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=[types.Content(parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096,
            ),
        ),
    )

    text = ""
    try:
        text = response.text or ""
    except (ValueError, AttributeError):
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text

    text = text.strip()
    bracket_pos = text.find("[")
    if bracket_pos == -1:
        return []
    text = text[bracket_pos:]
    last_bracket = text.rfind("]")
    if last_bracket > 0:
        text = text[:last_bracket + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        last_brace = text.rfind("}")
        if last_brace > 0:
            try:
                return json.loads(text[:last_brace + 1] + "]")
            except json.JSONDecodeError:
                pass
    return []


def _normalize_timestamp(ts: str) -> str:
    """MM:SS → 00:MM:SS, 이미 HH:MM:SS면 그대로 반환."""
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return f"00:{parts[0].zfill(2)}:{parts[1].zfill(2)}"
    elif len(parts) == 3:
        return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{parts[2].zfill(2)}"
    return "00:00:00"
