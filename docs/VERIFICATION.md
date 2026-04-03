# ClipForge 코드 검증 보고서

> **검증일**: 2026-03-28
> **상태**: 검증 완료 (4건 수정 후 확정)

---

## 1. 발견된 문제 및 수정 내역

### 문제 1 (CRITICAL): FFmpeg 클립 컷 타임스탬프 오류

| 항목 | 내용 |
|------|------|
| **파일** | `providers/ffmpeg.py` → `cut_clip()` |
| **문제** | `-ss`를 `-i` 앞에 배치하면 `-to`가 **상대값**(출력 시작 기준)이 됨. 예: start=01:30, end=02:45일 때 1분15초가 아닌 2분45초 클립이 생성됨 |
| **수정** | `-i input -ss start -to end` 순서로 변경. 절대 타임스탬프 기반 정밀 컷 |
| **영향** | 모든 클립의 길이가 정확해짐 |

### 문제 2 (CRITICAL): 파일 업로드 저장 누락

| 항목 | 내용 |
|------|------|
| **파일** | `ui/pages/input_page.py` → `on_upload()` |
| **문제** | NiceGUI 업로드 이벤트에서 `e.name`(파일명)만 저장하고 실제 파일 바이트를 디스크에 쓰지 않음. 파이프라인에서 파일을 찾을 수 없음 |
| **수정** | `e.content.read()`로 바이트를 읽어 `output/uploads/` 디렉토리에 저장. 전체 경로를 파이프라인에 전달 |
| **영향** | 로컬 파일 업로드가 정상 작동 |

### 문제 3 (MODERATE): 미디어 파일 서빙 API 오류

| 항목 | 내용 |
|------|------|
| **파일** | `ui/pages/result_page.py` |
| **문제** | `app.add_media_file()` (단수)는 NiceGUI에 존재하지 않음. 개별 파일이 아닌 디렉토리 단위로 서빙해야 함 |
| **수정** | `app.add_media_files()` (복수)로 변경. `final/`, `shorts/` 디렉토리를 URL 경로에 매핑 |
| **영향** | 결과 페이지에서 영상 미리보기 정상 재생 |

### 문제 4 (MINOR): 다운로드 시 final 폴더가 없는 경우 폴백 누락

| 항목 | 내용 |
|------|------|
| **파일** | `ui/pages/result_page.py` → `_download_all()`, `_download_selected()` |
| **문제** | 자막 OFF일 때 `final/` 디렉토리가 아닌 `shorts/`에 파일이 있는데, 다운로드 함수가 `final/`만 확인 |
| **수정** | `final/` 파일 없으면 `shorts/`에서 폴백 탐색 |
| **영향** | 자막 OFF 모드에서도 다운로드 정상 작동 |

---

## 2. 검증 항목별 결과

### 파이프라인 흐름

| 단계 | 파일 | 검증 | 상태 |
|------|------|------|------|
| Step 1: 다운로드 | `step1_download.py` | yt-dlp 옵션, 비동기 래핑, 진행률 콜백, 파일 탐색 | OK |
| Step 2: 분석 | `step2_analyze.py` | Gemini 업로드, 대기 루프, JSON 파싱, Highlight 변환 | OK |
| Step 3: 추출 | `step3_extract.py` | FFmpeg cut_clip 호출, 비동기 래핑, 경로 관리 | OK (수정 후) |
| Step 4: 템플릿 | `step4_template.py` | apply_template 호출, 제목/기관명 전달 | OK |
| Step 5: 자막 | `step5_subtitle.py` | 오디오 추출→Whisper 전사→burn-in, 임시파일 정리 | OK |
| Step 6: 출력 | `step6_output.py` | metadata.json 저장, 파일 크기 계산 | OK |

### 엔진/컨텍스트

| 항목 | 검증 | 상태 |
|------|------|------|
| `engine.py` | 스텝 순차 실행, 자막 OFF 건너뛰기, 에러 처리 | OK |
| `context.py` | 디렉토리 자동 생성, 진행률 계산, URL 감지 | OK |
| `config.py` | .env + config.yaml 로드, 폰트 폴백 | OK |

### Provider

| 항목 | 검증 | 상태 |
|------|------|------|
| `ffmpeg.py` | cut_clip(수정됨), apply_template, burn_subtitles, get_duration, extract_audio | OK |
| `gemini.py` | 업로드→대기→분석→JSON 파싱→파일 정리, 프롬프트 구조 | OK |
| `whisper_client.py` | 25MB 분할 처리, SRT 병합 타임스탬프 오프셋, _ms_to_srt | OK |
| `youtube.py` | OAuth 인증, resumable upload, check_auth | OK |

### UI 페이지

| 항목 | 검증 | 상태 |
|------|------|------|
| `input_page.py` | URL/파일 입력, 설정, 유효성 검사 | OK (수정 후) |
| `progress_page.py` | 실시간 진행률, 단계별 아이콘, 에러 표시 | OK |
| `result_page.py` | 카드 그리드, 미디어 서빙, 선택/다운로드 | OK (수정 후) |
| `upload_page.py` | YouTube 인증 확인, 클립별 설정, 업로드 실행 | OK |

### FFmpeg 필터 체인 검증

```
scale=1080:-2                    → 가로 1080 맞춤, 높이 비율 유지, 짝수 보정
pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color='#1B2A4A'  → 9:16 캔버스, 중앙 배치, 네이비 배경
drawtext (상단)                  → 제목, 흰색 54px, 중앙정렬, y=80, border 3px
drawtext (하단)                  → 기관명, 회색 38px, 중앙정렬, y=h-120, border 2px
```

→ 필터 체인 순서 및 파라미터 정확함

### 의존성 호환성

| 패키지 | 용도 | 호환성 |
|--------|------|--------|
| nicegui>=2.0 | Web UI | Python 3.11+ 호환 |
| yt-dlp | YouTube 다운로드 | 활발히 유지보수 |
| google-generativeai>=0.8 | Gemini API | 영상 업로드 지원 |
| openai>=1.0 | Whisper API | SRT 형식 응답 지원 |
| google-api-python-client | YouTube API | 안정적 |

---

## 3. 잠재적 주의사항 (버그는 아니나 운영 시 인지 필요)

| 항목 | 설명 | 대응 |
|------|------|------|
| Gemini 영상 길이 제한 | 1시간 이상 영상은 Gemini 컨텍스트 초과 가능 | config.yaml의 `max_video_duration` 으로 사전 검증 필요 (미구현, Post-MVP) |
| Whisper 25MB 분할 | 장시간 클립의 오디오가 25MB 초과 시 분할 전사 | 이미 `_transcribe_chunks`로 처리됨 |
| YouTube OAuth 7일 만료 | 테스트 모드에서 refresh_token 7일 만료 | 프로덕션 게시 시 해결됨 |
| `app.py` storage_secret | 하드코딩된 비밀키 | `.env`에서 읽도록 개선 권장 |
| 한국어 폰트 | Pretendard-Bold.otf를 `fonts/`에 직접 배치해야 함 | 없으면 맑은고딕 Bold 폴백 |
| 동시 사용자 | NiceGUI는 소규모 동시 접속에 적합 | 대규모 서비스 시 FastAPI+React 전환 필요 |

---

## 4. 최종 확인

| 항목 | 결과 |
|------|------|
| 전체 파일 수 | 27개 |
| 발견된 문제 | 4건 (모두 수정 완료) |
| 미해결 이슈 | 0건 |
| 코드 실행 준비 상태 | **Ready** (.env 설정 + FFmpeg 설치 후 실행 가능) |

---

## 5. 실행 전 체크리스트

```
[ ] Python 3.11+ 설치 확인
[ ] pip install -r requirements.txt
[ ] FFmpeg 설치 및 PATH 등록 (ffmpeg --version 확인)
[ ] .env 파일 생성 (.env.example 복사 후 API 키 입력)
    [ ] GEMINI_API_KEY
    [ ] OPENAI_API_KEY
[ ] (선택) fonts/Pretendard-Bold.otf 배치
[ ] (YouTube 업로드 사용 시) Google Cloud Console에서:
    [ ] YouTube Data API v3 활성화
    [ ] OAuth 2.0 클라이언트 ID 생성 → client_secret.json 다운로드
[ ] python app.py 실행 → http://localhost:8080 접속
```

---

## 6. 파일 구조 (최종)

```
쇼츠제작봇/
├── app.py                          # 진입점 (python app.py → :8080)
├── config.py                       # .env + config.yaml 로더
├── config.yaml                     # 템플릿/API 기본 설정
├── .env.example                    # API 키 템플릿
├── .gitignore
├── requirements.txt
│
├── docs/
│   ├── PRD.md                      # 제품 요구사항 문서
│   └── VERIFICATION.md             # 본 검증 문서
│
├── pipeline/
│   ├── engine.py                   # 6단계 오케스트레이터
│   ├── context.py                  # PipelineContext (공유 상태)
│   └── steps/
│       ├── step1_download.py       # yt-dlp 다운로드
│       ├── step2_analyze.py        # Gemini 하이라이트 분석
│       ├── step3_extract.py        # FFmpeg 클립 컷
│       ├── step4_template.py       # 9:16 네이비 템플릿
│       ├── step5_subtitle.py       # Whisper 자막 + burn-in
│       └── step6_output.py         # 메타데이터 저장
│
├── providers/
│   ├── ffmpeg.py                   # FFmpeg 명령 빌더
│   ├── gemini.py                   # Gemini 2.0 Flash API
│   ├── whisper_client.py           # OpenAI Whisper API
│   └── youtube.py                  # YouTube Data API v3
│
├── ui/
│   ├── pages/
│   │   ├── input_page.py           # 입력 (URL/파일/설정)
│   │   ├── progress_page.py        # 실시간 진행률
│   │   ├── result_page.py          # 클립 카드 선택
│   │   └── upload_page.py          # YouTube 업로드
│   └── components/
│       └── clip_card.py            # 클립 카드 컴포넌트
│
├── output/                         # 생성 결과물 (gitignore)
└── fonts/                          # 커스텀 폰트 (gitignore)
```
