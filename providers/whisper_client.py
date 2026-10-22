"""OpenAI Whisper API — 음성 전사 및 SRT 자막 생성."""
from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from config import settings

# Whisper API 파일 크기 제한 (25MB)
MAX_FILE_SIZE = 25 * 1024 * 1024


def _segment_dict(s, offset: float = 0.0) -> dict:
    """verbose_json 세그먼트(dict 또는 객체)를 dict로 변환한다.

    no_speech_prob / avg_logprob / compression_ratio는 음악·무음에서
    지어낸 문장(환각)을 걸러내는 데 쓴다.
    """
    get = s.get if isinstance(s, dict) else lambda k, d=None: getattr(s, k, d)
    return {
        "start": get("start") + offset,
        "end": get("end") + offset,
        "text": (get("text", "") or "").strip(),
        "no_speech_prob": get("no_speech_prob", 0.0),
        "avg_logprob": get("avg_logprob", 0.0),
        "compression_ratio": get("compression_ratio", 0.0),
    }


def transcribe_full(audio_path: Path) -> dict:
    """전체 오디오를 전사하여 segment-level 타임스탬프를 반환한다.

    Returns:
        {"text": str, "segments": [{"start", "end", "text", "no_speech_prob",
                                    "avg_logprob", "compression_ratio"}, ...]}
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    file_size = audio_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        return _transcribe_full_chunks(audio_path, client)

    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=settings.WHISPER_MODEL,
            file=f,
            response_format="verbose_json",
            language=settings.WHISPER_LANG,
            timestamp_granularities=["segment"],
        )

    segments = [_segment_dict(s) for s in (result.segments or [])]
    return {"text": result.text, "segments": segments}


def _transcribe_full_chunks(audio_path: Path, client: OpenAI) -> dict:
    """25MB 초과 파일을 분할하여 verbose_json 전사."""
    import subprocess
    import tempfile

    duration_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    total_duration = float(subprocess.run(
        duration_cmd, capture_output=True, text=True
    ).stdout.strip())

    chunk_duration = 600  # 10분 단위
    all_segments = []
    all_text = []
    offset = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        while offset < total_duration:
            chunk_path = Path(tmp_dir) / f"chunk_{offset}.wav"
            subprocess.run([
                "ffmpeg", "-y",
                "-ss", str(offset),
                "-i", str(audio_path),
                "-t", str(chunk_duration),
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(chunk_path),
            ], capture_output=True)

            with open(chunk_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model=settings.WHISPER_MODEL,
                    file=f,
                    response_format="verbose_json",
                    language=settings.WHISPER_LANG,
                    timestamp_granularities=["segment"],
                )

            all_segments.extend(_segment_dict(s, offset) for s in (result.segments or []))
            all_text.append(result.text)
            offset += chunk_duration

    return {"text": " ".join(all_text), "segments": all_segments}


def transcribe_to_srt(audio_path: Path, output_srt: Path) -> Path:
    """오디오 파일을 전사하여 SRT 자막 파일을 생성한다."""
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    file_size = audio_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        return _transcribe_chunks(audio_path, output_srt, client)

    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=settings.WHISPER_MODEL,
            file=f,
            response_format="srt",
            language=settings.WHISPER_LANG,
        )

    output_srt.write_text(result, encoding="utf-8")
    return output_srt


def _transcribe_chunks(audio_path: Path, output_srt: Path, client: OpenAI) -> Path:
    """25MB 초과 파일을 분할하여 전사."""
    import subprocess
    import tempfile

    duration_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    total_duration = float(subprocess.run(
        duration_cmd, capture_output=True, text=True
    ).stdout.strip())

    # 10분 단위로 분할
    chunk_duration = 600
    chunks = []
    offset = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        while offset < total_duration:
            chunk_path = Path(tmp_dir) / f"chunk_{offset}.wav"
            subprocess.run([
                "ffmpeg", "-y",
                "-ss", str(offset),
                "-i", str(audio_path),
                "-t", str(chunk_duration),
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(chunk_path),
            ], capture_output=True)

            with open(chunk_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model=settings.WHISPER_MODEL,
                    file=f,
                    response_format="srt",
                    language=settings.WHISPER_LANG,
                )
            chunks.append((offset, result))
            offset += chunk_duration

    # SRT 병합 (타임스탬프 오프셋 적용)
    merged = _merge_srt_chunks(chunks)
    output_srt.write_text(merged, encoding="utf-8")
    return output_srt


def _merge_srt_chunks(chunks: list[tuple[float, str]]) -> str:
    """분할된 SRT 청크를 하나로 병합한다."""
    import re

    all_entries = []
    counter = 1

    for offset_sec, srt_text in chunks:
        entries = srt_text.strip().split("\n\n")
        for entry in entries:
            lines = entry.strip().split("\n")
            if len(lines) < 3:
                continue
            # 타임스탬프 파싱 및 오프셋 적용
            ts_match = re.match(
                r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})",
                lines[1],
            )
            if not ts_match:
                continue

            g = [int(x) for x in ts_match.groups()]
            start_ms = (g[0] * 3600 + g[1] * 60 + g[2]) * 1000 + g[3] + int(offset_sec * 1000)
            end_ms = (g[4] * 3600 + g[5] * 60 + g[6]) * 1000 + g[7] + int(offset_sec * 1000)

            text = "\n".join(lines[2:])
            all_entries.append((counter, _ms_to_srt(start_ms), _ms_to_srt(end_ms), text))
            counter += 1

    return "\n\n".join(
        f"{idx}\n{start} --> {end}\n{text}"
        for idx, start, end, text in all_entries
    )


def _ms_to_srt(ms: int) -> str:
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    ms_rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"
