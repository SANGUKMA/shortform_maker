"""Claude Haiku — 전사본 기반 하이라이트 선택 + YouTube 메타데이터 생성 (anthropic SDK).

LLM은 구간을 문장 번호로만 고른다. 실제 시각은 호출 측이 Whisper 세그먼트에서 계산한다.
"""
from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel

from config import settings

_log = logging.getLogger(__name__)


class ClipPick(BaseModel):
    start_seg: int
    end_seg: int
    title_line1: str
    title_line2: str
    summary: str
    score: int
    reason: str
    description: str
    tags: list[str]


class HighlightResult(BaseModel):
    clips: list[ClipPick]


SYSTEM_PROMPT = """당신은 강연·세미나 영상을 YouTube 쇼츠로 재가공하는 편집자입니다.
번호가 붙은 전사본을 읽고, 따로 떼어 봐도 이해되는 하이라이트 구간을 고릅니다.
구간은 문장 번호(start_seg, end_seg)로만 지정합니다. 실제 시각은 프로그램이 문장 번호로 계산합니다."""


def _fmt_time(sec: float) -> str:
    """seconds → M:SS 또는 H:MM:SS (전사본 표시용)."""
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _build_prompt(
    segments: list[dict],
    clip_duration: str,
    clip_count: int | str,
    video_title: str,
    org_name: str,
) -> str:
    if clip_duration == "short":
        length_guide = "각 클립은 30~60초"
    else:
        length_guide = "각 클립은 1~6분"

    max_count = clip_count if isinstance(clip_count, int) else 10
    count_guide = (
        f"쇼츠로 쓸 만한 구간을 최대 {max_count}개 고르세요. "
        "쓸 만한 구간이 부족하면 더 적게 골라도 되고, 없으면 빈 목록을 돌려주세요."
    )

    transcript = "\n".join(
        f"[{i}] {_fmt_time(s['start'])}~{_fmt_time(s['end'])} {s['text']}"
        for i, s in enumerate(segments)
    )

    return f"""원본 영상: "{video_title}"
채널명: "{org_name}"

구간 선택 규칙:
- {length_guide}입니다. 각 문장 앞의 시작~끝 시각으로 길이를 가늠하세요.
- {count_guide}
- 클립끼리 문장이 겹치면 안 됩니다.
- start_seg는 생각이나 주제가 시작되는 문장, end_seg는 말이 완결되는 문장이어야 합니다.
- 첫 문장이 앞 내용을 가리키는 말("그래서", "이것이" 등)에 기대지 않아 독립적으로 이해되어야 합니다.
- 찬양·노래 가사, 광고 문구, 의미 없는 반복처럼 사람이 말하는 내용이 아닌 구간은 고르지 마세요.
- 음악·무음 구간은 전사본에서 빠져 있습니다. 앞뒤 문장의 시각이 크게 건너뛰는 곳을 걸쳐서 고르지 마세요.
- score는 0~100, 쇼츠로서 시청자의 관심을 끌 가능성입니다.

제목 규칙:
- title_line1: 핵심 키워드 (8자 이내, 예: "충격 발언!")
- title_line2: 부연 설명 (8자 이내, 예: "군중의 변심")
- 두 줄이 합쳐서 하나의 의미를 전달해야 합니다.
- summary, reason: 각각 20자 이내

YouTube 메타데이터 규칙:
- description: YouTube Shorts 설명 3~5줄. 첫 줄은 클립 핵심 내용 한 문장, 원본 영상과 채널({org_name}) 안내, 구독 유도, 마지막 줄에 해시태그 3~5개(#숏츠 #Shorts 포함)
- tags: 검색 최적화용 키워드, 한국어+영어 혼합, 최대 10개

전사본 ([문장 번호] 시작~끝 텍스트):
{transcript}"""


async def select_highlights(
    segments: list[dict],
    clip_duration: str = "short",
    clip_count: int | str = "auto",
    video_title: str = "",
    org_name: str = "",
) -> list[ClipPick]:
    """전사본 문장 목록에서 하이라이트 구간(문장 번호 범위)과 메타데이터를 고른다."""
    # 키가 비어 있으면 None을 넘겨 SDK가 환경변수/로그인 프로필에서 찾게 한다
    client = anthropic.AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY or None,
        max_retries=4,
    )
    prompt = _build_prompt(segments, clip_duration, clip_count, video_title, org_name)

    async with client.messages.stream(
        model=settings.CLAUDE_MODEL,
        max_tokens=32000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_format=HighlightResult,
    ) as stream:
        message = await stream.get_final_message()

    _log.info(
        "Claude 응답: stop_reason=%s, 입력 %d토큰, 출력 %d토큰",
        message.stop_reason, message.usage.input_tokens, message.usage.output_tokens,
    )
    if message.stop_reason == "refusal":
        raise RuntimeError("Claude가 이 전사본의 처리를 거절했습니다.")
    if message.stop_reason == "max_tokens":
        raise RuntimeError("Claude 응답이 최대 길이에서 잘렸습니다.")
    if message.parsed_output is None:
        raise RuntimeError("Claude 응답을 해석하지 못했습니다.")

    return message.parsed_output.clips
