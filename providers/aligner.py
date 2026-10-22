"""wav2vec2 강제 정렬 — 클립 경계를 문장의 실제 첫/마지막 음절 위치로 보정 (선택 기능).

Whisper 문장 시각은 앞뒤로 1초 가까이 어긋나 말끝이 잘리거나 다음 문장이 섞인다.
경계 근처 오디오에 문장 글자를 맞춰(CTC 강제 정렬) 음절 위치를 찾고,
그 사이에서 소리가 잦아드는 지점을 골라 자른다.

PyTorch·transformers가 필요해 로컬에서만 켠다 (.env의 ALIGN_ENABLED, requirements-align.txt).
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

from config import settings

_log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SEC = 0.02          # wav2vec2 출력 프레임 간격 (320샘플)
HOP_SEC = 0.01            # 소리 크기 분석 간격
MIN_PAUSE = 0.12          # 이보다 짧은 저음량 구간은 쉼으로 보지 않는다
SEARCH_SEC = 1.0          # 마지막/첫 음절에서 쉼을 찾는 최대 거리
PAD_SEC = 0.15            # 쉼 안쪽으로 들어가 자르는 여유
MARGIN_SEC = 3.0          # 정렬 창 앞뒤 여유 (Whisper 시각은 1~2초씩 통째로 밀리기도 한다)
CONTEXT_GAP = 5.0         # 이웃 문장이 이보다 멀면(음악·무음을 뺀 자리) 문맥에 넣지 않는다
STAR_PENALTY = 1.0        # 창 가장자리의 글자 없는 말소리를 흡수하는 상태의 감점 (로그 확률)

_model = None             # (feature_extractor, model, vocab, blank_id, delim_id)


def _load():
    global _model
    if _model is None:
        import torch  # noqa: F401  # 설치 확인
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC

        fe = Wav2Vec2FeatureExtractor.from_pretrained(settings.ALIGN_MODEL)
        model = Wav2Vec2ForCTC.from_pretrained(settings.ALIGN_MODEL).eval()
        vocab = _load_vocab(settings.ALIGN_MODEL)
        _model = (fe, model, vocab, vocab["[PAD]"], vocab.get("|"))
        _log.info("정렬 모델 로드: %s (어휘 %d개)", settings.ALIGN_MODEL, len(vocab))
    return _model


def _load_vocab(model_id: str) -> dict[str, int]:
    import json
    from huggingface_hub import hf_hub_download
    return json.loads(Path(hf_hub_download(model_id, "vocab.json")).read_text(encoding="utf-8"))


def load_audio(path: Path) -> np.ndarray:
    """16kHz mono pcm_s16le WAV(extract_audio 출력) → float32 배열."""
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def _tokens(text: str, vocab: dict[str, int], delim: int | None) -> list[int]:
    """모델 어휘에 있는 음절만 토큰으로 (숫자·영문·문장부호는 건너뜀)."""
    out: list[int] = []
    for ch in text:
        if ch.isspace():
            if delim is not None and out and out[-1] != delim:
                out.append(delim)
        elif ch in vocab:
            out.append(vocab[ch])
    while out and out[-1] == delim:
        out.pop()
    return out


def _emission(audio: np.ndarray) -> np.ndarray:
    import torch
    fe, model, *_ = _load()
    inputs = fe(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
    with torch.inference_mode():
        logits = model(inputs.input_values).logits[0]
    return torch.log_softmax(logits, dim=-1).numpy()


def _force_align(em: np.ndarray, tokens: list[int], blank: int) -> list[tuple[int, int]] | None:
    """CTC 비터비 정렬 — 토큰마다 (시작 프레임, 끝 프레임).

    첫 토큰 전·마지막 토큰 뒤에는 아무 말소리나 흡수하는 상태를 둬서,
    창 가장자리에 걸린 앞뒤 문장 때문에 글자가 억지로 당겨지지 않게 한다.
    """
    T, N = len(em), len(tokens)
    if N == 0 or T < N:
        return None
    NEG = -1e30
    tok = em[:, tokens]                                   # (T, N)
    nonblank = np.delete(em, blank, axis=1)
    star = np.maximum(em[:, blank], nonblank.max(axis=1) - STAR_PENALTY)
    trellis = np.full((T, N + 1), NEG)
    adv = np.zeros((T, N + 1), dtype=bool)
    trellis[0, 0] = star[0]
    trellis[0, 1] = tok[0, 0]
    adv[0, 1] = True
    for t in range(1, T):
        prev = trellis[t - 1]
        stay = prev.copy()
        stay[0] += star[t]
        stay[1:] += np.maximum(em[t, blank], tok[t])       # 공백 또는 같은 토큰 반복
        stay[N] = prev[N] + max(star[t], tok[t, N - 1])
        move = np.full(N + 1, NEG)
        move[1:] = prev[:-1] + tok[t]
        adv[t] = move > stay
        trellis[t] = np.maximum(move, stay)

    # 역추적: 프레임별 상태(지금까지 낸 토큰 수)
    path = np.zeros(T, dtype=int)
    j = N
    for t in range(T - 1, -1, -1):
        path[t] = j
        if adv[t, j]:
            j -= 1
    if j != 0:
        return None

    spans = []
    for k in range(N):
        frames = np.nonzero((path == k + 1) & np.r_[True, path[:-1] == k])[0]
        start = int(frames[0]) if len(frames) else int(np.argmax(path >= k + 1))
        end = start
        while end + 1 < T and path[end + 1] == k + 1 and tok[end + 1, k] >= em[end + 1, blank]:
            end += 1
        spans.append((start, end))
    return spans


def _pauses(audio: np.ndarray) -> list[tuple[float, float]]:
    """창 안의 쉼(저음량 구간) 목록 (초, 창 기준). 기준 음량은 창 안 말소리에 맞춰 정한다."""
    hop = int(HOP_SEC * SAMPLE_RATE)
    n = len(audio) // hop
    if n == 0:
        return []
    rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))
    db = 20 * np.log10(rms + 1e-9)
    quiet = db < np.percentile(db, 90) - 25
    out, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) * HOP_SEC >= MIN_PAUSE:
                out.append((i * HOP_SEC, j * HOP_SEC))
            i = j
        else:
            i += 1
    return out


def refine_boundary(audio: np.ndarray, segs: list[dict], i: int) -> tuple[float | None, float | None]:
    """segs[i]와 segs[i+1] 사이 경계를 보정한다.

    Returns: (segs[i]가 실제로 끝나는 시각, segs[i+1]이 실제로 시작하는 시각).
    i == -1이면 첫 문장의 시작만, i == len(segs)-1이면 마지막 문장의 끝만 구한다.
    정렬할 수 없으면 해당 값은 None (호출 측은 Whisper 시각을 그대로 쓴다).
    """
    n = len(segs)

    def near(a: int, b: int) -> bool:
        return segs[b]["start"] - segs[a]["end"] <= CONTEXT_GAP

    if 0 <= i < n - 1 and not near(i, i + 1):
        # 경계 양쪽이 멀리 떨어져 있으면 각각 단독 경계(마지막 문장 끝 / 첫 문장 시작)로 처리
        end_cut, _ = refine_boundary(audio, segs[: i + 1], i)
        _, start_cut = refine_boundary(audio, segs[i + 1:], -1)
        return end_cut, start_cut

    _, _, vocab, blank, delim = _load()
    # 경계 앞뒤 두 문장씩 문맥으로 (멀리 떨어진 문장은 제외)
    lo = i - 1 if i >= 1 and near(i - 1, i) else max(i, 0)
    hi = i + 2 if i + 2 < n and near(i + 1, i + 2) else min(i + 1, n - 1)
    toks_by_seg = {k: _tokens(segs[k]["text"], vocab, delim) for k in range(lo, hi + 1)}
    tokens: list[int] = []
    first_idx: dict[int, int] = {}
    last_idx: dict[int, int] = {}
    for k in range(lo, hi + 1):
        if not toks_by_seg[k]:
            continue
        if tokens and delim is not None:
            tokens.append(delim)
        first_idx[k] = len(tokens)
        tokens += toks_by_seg[k]
        last_idx[k] = len(tokens) - 1

    dur = len(audio) / SAMPLE_RATE
    t0 = max(0.0, segs[lo]["start"] - MARGIN_SEC)
    t1 = min(dur, segs[hi]["end"] + MARGIN_SEC)
    window = audio[int(t0 * SAMPLE_RATE): int(t1 * SAMPLE_RATE)]
    spans = _force_align(_emission(window), tokens, blank)
    if spans is None:
        return None, None

    a_end = t0 + (spans[last_idx[i]][1] + 1) * FRAME_SEC if i in last_idx else None
    b_start = t0 + spans[first_idx[i + 1]][0] * FRAME_SEC if (i + 1) in first_idx else None
    pauses = [(t0 + p0, t0 + p1) for p0, p1 in _pauses(window)]

    end_cut = start_cut = None
    if a_end is not None:
        # 마지막 음절 뒤 첫 쉼 안에서 끝낸다 (모음 꼬리는 음량이 떨어지는 곳까지)
        limit = min(a_end + SEARCH_SEC, b_start if b_start is not None else t1)
        p = next(((p0, p1) for p0, p1 in pauses if p1 > a_end and p0 < limit), None)
        if p:
            s = max(p[0], a_end)
            end_cut = min(s + min(PAD_SEC, (p[1] - s) / 2), limit)
        else:
            end_cut = (a_end + b_start) / 2 if b_start is not None else min(a_end + 2 * PAD_SEC, t1)
    if b_start is not None:
        # 첫 음절 앞 마지막 쉼 안에서 시작한다
        limit = max(b_start - SEARCH_SEC, a_end if a_end is not None else t0)
        p = next(((p0, p1) for p0, p1 in reversed(pauses) if p0 < b_start and p1 > limit), None)
        if p:
            e = min(p[1], b_start)
            start_cut = max(e - min(PAD_SEC, (e - p[0]) / 2), limit)
        else:
            start_cut = (a_end + b_start) / 2 if a_end is not None else max(b_start - PAD_SEC, t0)
    return end_cut, start_cut
