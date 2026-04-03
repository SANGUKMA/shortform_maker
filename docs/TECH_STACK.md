# ClipForge 기술 스택 점검 보고서

> **점검일**: 2026-03-28
> **환경**: Windows 11 Home 10.0.26200 / Anaconda Python

---

## 1. 시스템 환경

| 항목 | 필요 버전 | 현재 버전 | 상태 |
|------|----------|----------|------|
| Python | 3.11+ | 3.12.7 (Anaconda) | OK |
| FFmpeg | 설치 + PATH | 8.0.1-full_build | OK |
| ffprobe | 설치 + PATH | 8.0.1 | OK |
| OS | Windows / Linux / macOS | Windows 11 Home | OK |

### FFmpeg 주요 인코더/필터 지원 현황

| 기능 | 필요 여부 | 지원 | 용도 |
|------|----------|------|------|
| libx264 | 필수 | OK | H.264 CPU 인코딩 |
| h264_nvenc | 선택 (GPU) | OK | NVIDIA GPU 가속 인코딩 |
| libass | 필수 | OK | 자막 burn-in (subtitles 필터) |
| libfreetype | 필수 | OK | drawtext 필터 (한국어 텍스트 오버레이) |
| aac | 필수 | OK | 오디오 인코딩 |
| pcm_s16le | 필수 | OK | Whisper용 오디오 추출 |

---

## 2. Python 패키지

### 설치 완료

| 패키지 | 필요 버전 | 현재 버전 | 용도 |
|--------|----------|----------|------|
| openai | >=1.0 | 1.75.0 | Whisper API (음성 전사) |
| google-api-python-client | >=2.0 | 2.193.0 | YouTube Data API v3 (업로드) |
| google-auth-oauthlib | >=1.0 | 1.3.0 | YouTube OAuth 인증 |
| google-auth-httplib2 | >=0.2 | 0.3.0 | YouTube API HTTP 전송 |
| pyyaml | >=6.0 | 6.0.1 | config.yaml 로드 |
| python-dotenv | >=1.0 | 1.2.2 | .env 환경변수 로드 |
| aiofiles | >=23.0 | 23.2.1 | 비동기 파일 I/O |

### 미설치 (설치 필요)

| 패키지 | 필요 버전 | 용도 | 설치 명령 |
|--------|----------|------|----------|
| **nicegui** | >=2.0 | Web UI (입력/진행/결과/업로드 페이지) | `pip install nicegui` |
| **yt-dlp** | >=2024.0 | YouTube 영상 다운로드 + 자막 추출 | `pip install yt-dlp` |
| **google-generativeai** | >=0.8 | Gemini 2.0 Flash API (하이라이트 분석) | `pip install google-generativeai` |

### 설치 명령어 (일괄)

```bash
pip install nicegui yt-dlp google-generativeai
```

---

## 3. API 키 및 인증

### 필수 API 키

| 서비스 | 환경변수 | 용도 | 발급처 | 현재 상태 |
|--------|---------|------|--------|----------|
| Google AI (Gemini) | `GEMINI_API_KEY` | 영상 하이라이트 분석 | https://aistudio.google.com/apikey | .env 미생성 |
| OpenAI (Whisper) | `OPENAI_API_KEY` | 음성 전사 → SRT 자막 | https://platform.openai.com/api-keys | .env 미생성 |

### 선택 (YouTube 업로드 시)

| 항목 | 환경변수 | 용도 | 발급처 | 현재 상태 |
|------|---------|------|--------|----------|
| YouTube OAuth | `YOUTUBE_CLIENT_SECRET` | YouTube 영상 업로드 | Google Cloud Console | 미확인 |
| OAuth 토큰 | `YOUTUBE_TOKEN_PATH` | 인증 토큰 저장 경로 | 최초 실행 시 자동 생성 | - |

### .env 파일 생성 방법

```bash
# 프로젝트 루트에서
cp .env.example .env
```

```env
# .env 내용
GEMINI_API_KEY=여기에_제미나이_API_키
OPENAI_API_KEY=여기에_오픈AI_API_키
YOUTUBE_CLIENT_SECRET=client_secret.json
YOUTUBE_TOKEN_PATH=token.pickle
```

---

## 4. 폰트

| 폰트 | 경로 | 용도 | 상태 |
|------|------|------|------|
| Pretendard Bold | `fonts/Pretendard-Bold.otf` | 기본 폰트 (제목/기관명) | 미배치 (선택) |
| 맑은 고딕 Bold | `C:/Windows/Fonts/malgunbd.ttf` | 폴백 폰트 | OK (Windows 내장) |

→ Pretendard 폰트 없이도 맑은 고딕 Bold로 자동 폴백되므로 즉시 실행 가능

---

## 5. 기술 스택 아키텍처 요약

```
┌─────────────────────────────────────────────────────┐
│                    사용자 브라우저                      │
│                  http://localhost:8080                │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              NiceGUI (Python Web UI)                 │
│  입력 → 진행 → 결과선택 → 업로드설정                    │
│  내장: FastAPI + Tailwind CSS + WebSocket             │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Pipeline Engine (Python)                 │
│                                                      │
│  Step 1 ─── yt-dlp ──────────── YouTube 다운로드      │
│  Step 2 ─── Gemini 2.0 Flash ── 하이라이트 분석       │
│  Step 3 ─── FFmpeg ──────────── 클립 추출             │
│  Step 4 ─── FFmpeg ──────────── 템플릿 합성           │
│  Step 5 ─── Whisper + FFmpeg ── 자막 생성/burn-in     │
│  Step 6 ─── YouTube API v3 ──── 업로드               │
│                                                      │
└──────────────────────────────────────────────────────┘

외부 API:
  ├── Google AI (Gemini 2.0 Flash)  ─ 영상 분석
  ├── OpenAI (Whisper)              ─ 음성 전사
  └── YouTube Data API v3           ─ 영상 업로드

로컬 도구:
  ├── FFmpeg 8.0.1                  ─ 영상 편집 엔진
  ├── ffprobe                       ─ 영상 메타데이터
  └── yt-dlp                        ─ YouTube 다운로드
```

---

## 6. 비용 구조

| 서비스 | 과금 단위 | 단가 | 10분 영상 5클립 기준 |
|--------|----------|------|---------------------|
| Gemini 2.0 Flash | 토큰 (영상 1초≈263토큰) | 입력 $0.10/1M, 출력 $0.40/1M | ~25원 |
| Whisper API | 오디오 분 | $0.006/분 | ~40원 (5분 전사) |
| YouTube Data API | 할당량 (units) | 무료 (10,000 units/일) | 무료 |
| FFmpeg | - | 무료 (로컬) | 무료 |
| yt-dlp | - | 무료 (오픈소스) | 무료 |
| NiceGUI | - | 무료 (오픈소스) | 무료 |
| **합계** | | | **~65원/회** |

### 월간 비용 추정

| 사용량 | 월 API 비용 |
|--------|------------|
| 월 50회 (10분 영상) | ~3,250원 |
| 월 100회 (10분 영상) | ~6,500원 |
| 월 100회 (30분 영상) | ~15,000원 |

---

## 7. 실행 전 체크리스트

```
[x] Python 3.11+             → 3.12.7 확인
[x] FFmpeg + PATH             → 8.0.1 확인
[x] ffprobe + PATH            → 8.0.1 확인
[x] openai                    → 1.75.0 확인
[x] google-api-python-client  → 2.193.0 확인
[x] google-auth-oauthlib      → 1.3.0 확인
[x] pyyaml                    → 6.0.1 확인
[x] python-dotenv             → 1.2.2 확인
[x] aiofiles                  → 23.2.1 확인
[x] 맑은 고딕 Bold 폰트        → Windows 내장 확인
[ ] nicegui                   → pip install nicegui
[ ] yt-dlp                    → pip install yt-dlp
[ ] google-generativeai       → pip install google-generativeai
[ ] .env 파일 생성             → cp .env.example .env + API 키 입력
[ ] (선택) client_secret.json → YouTube 업로드 사용 시 필요
```
