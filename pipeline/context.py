from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from config import OUTPUT_DIR


@dataclass
class Highlight:
    index: int
    title: str
    title_line1: str    # 제목 1줄 (흰색)
    title_line2: str    # 제목 2줄 (노란색)
    summary: str
    start: str          # "HH:MM:SS"
    end: str            # "HH:MM:SS"
    score: int          # 0-100
    reason: str = ""


@dataclass
class PipelineContext:
    source: str                                     # YouTube URL or local file path
    org_name: str                                   # 기관/채널명
    clip_duration: Literal["short", "mid"] = "short"  # short=~60s, mid=1~6min
    clip_count: int | str = "auto"                  # int or "auto"
    video_aspect: str = "16:9"                      # "16:9" or "5:4"
    subtitle_enabled: bool = True
    project_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # --- 파이프라인 실행 중 채워지는 필드 ---
    source_path: Path | None = None                 # 다운로드된 영상 경로
    source_srt: Path | None = None                  # 원본 자막 경로
    video_title: str = ""                           # 원본 영상 제목
    video_duration: int = 0                         # 원본 영상 길이(초)

    # --- 전사 결과 (문장 경계 스냅용) ---
    transcript_text: str = ""
    transcript_segments: list[dict] = field(default_factory=list)  # [{start, end, text}]
    full_audio_path: Path | None = None

    highlights: list[Highlight] = field(default_factory=list)
    clip_paths: list[Path] = field(default_factory=list)
    short_paths: list[Path] = field(default_factory=list)
    final_paths: list[Path] = field(default_factory=list)

    # --- 진행 상태 ---
    current_step: int = 0
    total_steps: int = 7
    step_progress: float = 0.0
    status_message: str = ""
    error: str | None = None

    @property
    def project_dir(self) -> Path:
        d = OUTPUT_DIR / self.project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def clips_dir(self) -> Path:
        d = self.project_dir / "clips"
        d.mkdir(exist_ok=True)
        return d

    @property
    def shorts_dir(self) -> Path:
        d = self.project_dir / "shorts"
        d.mkdir(exist_ok=True)
        return d

    @property
    def final_dir(self) -> Path:
        d = self.project_dir / "final"
        d.mkdir(exist_ok=True)
        return d

    @property
    def is_youtube_url(self) -> bool:
        return self.source.startswith(("http://", "https://"))

    @property
    def overall_progress(self) -> float:
        if self.total_steps == 0:
            return 0.0
        base = (self.current_step - 1) / self.total_steps
        step_part = self.step_progress / self.total_steps
        return min(base + step_part, 1.0)

    def update_progress(self, step: int, progress: float, message: str):
        self.current_step = step
        self.step_progress = progress
        self.status_message = message
