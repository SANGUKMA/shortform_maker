"""FFmpeg 명령 빌더 — 클립 컷, 템플릿 합성, 자막 burn-in."""
from __future__ import annotations

import subprocess
from pathlib import Path

from config import settings, FONTS_DIR


import logging

_log = logging.getLogger(__name__)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    _log.info("FFmpeg CMD: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        # FFmpeg stderr에서 진행률 로그를 제거하고 실제 에러만 추출
        stderr = result.stderr or ""
        error_lines = [
            line for line in stderr.splitlines()
            if not line.startswith("frame=") and line.strip()
        ]
        error_msg = "\n".join(error_lines[-30:]) if error_lines else stderr[-2000:]
        raise RuntimeError(f"FFmpeg 오류 (code {result.returncode}):\n{error_msg}")
    return result


def _ts_to_seconds(ts: str) -> float:
    """HH:MM:SS or MM:SS → seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0.0


def _verify_audio(path: str | Path, min_bitrate: int = 10000) -> bool:
    """출력 파일의 오디오 비트레이트가 정상인지 확인한다."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-select_streams", "a",
        "-show_entries", "stream=bit_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return int(result.stdout.strip()) > min_bitrate
    except (ValueError, TypeError):
        return False


def cut_clip(
    input_path: str | Path,
    output_path: str | Path,
    start: str,
    end: str,
    max_retries: int = 5,
) -> Path:
    """타임스탬프 기반 정밀 클립 컷 (재인코딩) + 오디오 검증 재시도.

    NiceGUI 웹서버 환경에서 간헐적으로 오디오가 묵음이 되는 문제를 방지하기 위해,
    추출 후 오디오 비트레이트를 검증하고 실패 시 자동 재시도한다.
    """
    import time

    duration = _ts_to_seconds(end) - _ts_to_seconds(start)
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-ss", start,
        "-i", str(input_path),
        "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-threads", "2",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]

    for attempt in range(1, max_retries + 1):
        _run(cmd)

        if _verify_audio(output_path):
            if attempt > 1:
                _log.info("오디오 정상 확인 (시도 %d회)", attempt)
            return Path(output_path)

        _log.warning("오디오 묵음 감지 (시도 %d/%d), 재시도...", attempt, max_retries)
        time.sleep(0.3)

    _log.error("오디오 묵음 %d회 재시도 후에도 해결 안 됨: %s", max_retries, output_path)
    return Path(output_path)


def apply_template(
    input_path: str | Path,
    output_path: str | Path,
    title_line1: str,
    title_line2: str,
    org_text: str,
    video_aspect: str = "16:9",
) -> Path:
    """9:16 세로 프레임 + 배경 + 2줄 제목(흰+노랑) + 기관명 + 선택적 로고.

    제목/기관명은 각각 상단/하단 영역의 수직 중앙에 배치.
    한국어 텍스트는 textfile= 으로 전달 (Windows 인코딩 이슈 방지).
    로고(PNG)가 설정되어 있으면 기관명 위에 배치.
    """
    font = settings.get_font().replace("\\", "/")
    ff = font.replace(":", "\\:")
    out_dir = Path(output_path).parent
    ch = settings.CANVAS_HEIGHT  # 1920
    cw = settings.CANVAS_WIDTH   # 1080

    # 비율에 따른 영상 높이, 폰트 크기 계산
    if video_aspect in ("5:4", "4:5"):
        vid_h = 1200  # 영상 높이 (상단/하단 네이비 각 360px)
        # 원본 16:9 영상을 9:10 비율로 center crop → 타겟 해상도로 scale
        scale_filter = f"crop=ih*9/10:ih,scale={cw}:{vid_h}"
        fs = 108      # 제목 (16:9와 동일)
        org_fs = 76   # 기관명 (16:9와 동일)
        line_gap = 60
    else:
        vid_h = cw * 9 // 16  # 608 (16:9)
        scale_filter = f"scale={cw}:{vid_h}"
        fs = settings.TITLE_FONT_SIZE  # 54
        org_fs = settings.ORG_FONT_SIZE  # 38
        line_gap = settings.TITLE_LINE_GAP  # 30

    top_area = (ch - vid_h) // 2       # 상단 배경 높이
    bottom_area = ch - top_area - vid_h  # 하단 배경 높이

    # 제목 2줄 수직 중앙 (상단 영역 기준)
    two_line_h = fs * 2 + line_gap
    title_y1 = (top_area - two_line_h) // 2
    title_y2 = title_y1 + fs + line_gap

    # 로고 확인
    logo_path = settings.ORG_LOGO_PATH
    has_logo = bool(logo_path) and Path(logo_path).exists()

    # 기관명 + 로고 수직 배치 (하단 영역 기준)
    if has_logo:
        logo_h = 80  # 로고 높이 (고정)
        logo_gap = 12  # 로고와 기관명 사이 간격
        combo_h = logo_h + logo_gap + org_fs
        combo_top = top_area + vid_h + (bottom_area - combo_h) // 2
        logo_y = combo_top
        org_y = combo_top + logo_h + logo_gap
    else:
        org_y = top_area + vid_h + (bottom_area - org_fs) // 2

    temp_files = []

    # drawtext 필터 파트 구성
    dt_parts = []

    # 제목 1줄 (흰색)
    if title_line1:
        f1 = out_dir / "_title1.txt"
        f1.write_text(title_line1, encoding="utf-8")
        temp_files.append(f1)
        p1 = str(f1).replace("\\", "/").replace(":", "\\:")
        dt_parts.append(
            f"drawtext=fontfile='{ff}':"
            f"textfile='{p1}':"
            f"fontsize={fs}:"
            f"fontcolor=white:"
            f"x=(w-text_w)/2:y={title_y1}:"
            f"shadowcolor=black@0.4:shadowx=2:shadowy=2"
        )

    # 제목 2줄 (진한 노란색)
    if title_line2:
        f2 = out_dir / "_title2.txt"
        f2.write_text(title_line2, encoding="utf-8")
        temp_files.append(f2)
        p2 = str(f2).replace("\\", "/").replace(":", "\\:")
        dt_parts.append(
            f"drawtext=fontfile='{ff}':"
            f"textfile='{p2}':"
            f"fontsize={fs}:"
            f"fontcolor=#FFD700:"
            f"x=(w-text_w)/2:y={title_y2}:"
            f"shadowcolor=black@0.4:shadowx=2:shadowy=2"
        )

    # 기관명 (하단)
    if org_text:
        f3 = out_dir / "_org.txt"
        f3.write_text(org_text, encoding="utf-8")
        temp_files.append(f3)
        p3 = str(f3).replace("\\", "/").replace(":", "\\:")
        dt_parts.append(
            f"drawtext=fontfile='{ff}':"
            f"textfile='{p3}':"
            f"fontsize={org_fs}:"
            f"fontcolor={settings.ORG_COLOR}:"
            f"x=(w-text_w)/2:y={org_y}:"
            f"shadowcolor=black@0.4:shadowx=2:shadowy=2"
        )

    if has_logo:
        # filter_complex: 영상 + 로고 2개 입력
        logo_str = str(logo_path).replace("\\", "/")
        vf_base = f"{scale_filter},pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color={settings.BG_COLOR}"
        dt_chain = ",".join(dt_parts)

        fc = (
            f"[0:v]{vf_base},{dt_chain}[main];"
            f"[1:v]scale=-1:{logo_h}[logo];"
            f"[main][logo]overlay=(W-w)/2:{logo_y}[vout]"
        )
        cmd = [
            "ffmpeg", "-nostdin", "-y",
            "-i", str(input_path),
            "-i", logo_str,
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "0:a:0",
            "-c:v", "libx264",
            "-preset", settings.VIDEO_PRESET,
            "-crf", str(settings.VIDEO_CRF),
            "-threads", "2",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
    else:
        # 기존 방식: -vf (단일 입력)
        vf_parts = [
            scale_filter,
            f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color={settings.BG_COLOR}",
        ] + dt_parts
        vf = ",".join(vf_parts)

        cmd = [
            "ffmpeg", "-nostdin", "-y",
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", settings.VIDEO_PRESET,
            "-crf", str(settings.VIDEO_CRF),
            "-threads", "2",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]

    try:
        _run(cmd)
    finally:
        for f in temp_files:
            f.unlink(missing_ok=True)

    return Path(output_path)


def burn_subtitles(
    input_path: str | Path,
    output_path: str | Path,
    srt_path: str | Path,
) -> Path:
    """SRT 자막을 영상에 하드코딩."""
    srt_str = str(srt_path).replace("\\", "/").replace(":", "\\:")
    force_style = (
        f"FontName={settings.SUB_FONT_NAME},"
        f"FontSize={settings.SUB_FONT_SIZE},"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"Outline={settings.SUB_OUTLINE},"
        f"Alignment=2,"
        f"MarginV={settings.SUB_MARGIN_V},"
        f"Bold=1"
    )
    fonts_dir = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
    vf = f"subtitles='{srt_str}':fontsdir='{fonts_dir}':force_style='{force_style}'"

    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", settings.VIDEO_PRESET,
        "-crf", str(settings.VIDEO_CRF),
        "-threads", "2",
        "-c:a", "copy",
        str(output_path),
    ]
    _run(cmd)
    return Path(output_path)


def get_duration(input_path: str | Path) -> float:
    """영상 길이(초) 반환."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def extract_audio(input_path: str | Path, output_path: str | Path) -> Path:
    """영상에서 오디오만 추출 (Whisper 입력용)."""
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_path),
    ]
    _run(cmd)
    return Path(output_path)
