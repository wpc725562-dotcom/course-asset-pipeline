"""Audio-level duplicate detection via RMS-envelope cross-correlation.

Problem this solves
-------------------
Two uploads of the *same lecture* can carry completely different titles, so
string comparison cannot tell you they are duplicates:

    P1   第一章 行列式 一、行列式的概念+二、行列式的性质     [63 min]
    P14  【字幕版】第一章 行列式一、二-全                    [63 min]

The durations match to the second, but the wording does not. What *is* stable
is the audio. So we compare the recordings themselves.

Method
------
1. Take a window at the midpoint of each file (``win_sec``).
2. Decode to mono PCM, compute an RMS energy envelope at 20 ms granularity.
3. Normalized cross-correlation over a search window of ``max_shift`` frames.

Two parameter choices carry all the weight, and both were wrong in the first
implementation (see ``docs/design-notes.md``):

* ``WIN_SEC`` must be ~90 s. A 40 s window has too little envelope structure and
  unrelated speech can correlate at 0.2-0.3 by chance.
* ``MAX_SHIFT`` must be ~25 s. If the two uploads differ by 14 s in total
  duration (a trimmed intro), the midpoint is offset by ~7 s. A +/-3 s search
  window reports ~0.25 for *identical* recordings -- a false negative.

Always run a negative control (two different lectures from the same course) to
calibrate the thresholds on your own corpus.
"""

from __future__ import annotations

import numpy as np

FRAMES_PER_SEC = 50          # 20 ms per frame
WIN_SEC = 90                 # analysis window length
MAX_SHIFT = 1250             # +/- 25 s alignment search
SAME_THRESHOLD = 0.70        # >= this: same recording
PARTIAL_THRESHOLD = 0.35     # >= this: partially related (e.g. different edit)

VERDICT_SAME = "same"
VERDICT_PARTIAL = "partial"
VERDICT_DIFFERENT = "different"


def envelope(path: str, win_sec: int = WIN_SEC, frames_per_sec: int = FRAMES_PER_SEC) -> np.ndarray:
    """Return the RMS envelope of a window centred on the file's midpoint."""
    import av

    with av.open(path) as c:
        dur = c.duration / av.time_base
        start = max(0.0, dur / 2 - win_sec / 2)
        stream = c.streams.audio[0]
        sr = stream.rate
        step = max(1, sr // frames_per_sec)
        c.seek(int(start * av.time_base), any_frame=False)

        vals: list[float] = []
        buf: list[float] = []
        for frame in c.decode(stream):
            a = frame.to_ndarray()
            if a.ndim > 1:
                a = a.mean(axis=0)
            for x in a.astype(np.float32):
                buf.append(float(x))
                if len(buf) >= step:
                    vals.append(float(np.sqrt(np.mean(np.square(buf)))))
                    buf = []
            if len(vals) >= win_sec * frames_per_sec:
                break
    return np.asarray(vals)


def best_corr(a: np.ndarray, b: np.ndarray, max_shift: int = MAX_SHIFT) -> tuple[float | None, int]:
    """Normalized cross-correlation of two envelopes over a shift search.

    Returns ``(coefficient, best_shift_frames)``; coefficient is None when the
    envelopes are too short to be meaningful.
    """
    if len(a) < 50 or len(b) < 50:
        return None, 0
    m = min(len(a), len(b))
    a = a[:m] - a[:m].mean()
    b = b[:m] - b[:m].mean()
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return None, 0

    best, best_shift = -1.0, 0
    for s in range(-max_shift, max_shift + 1):
        if s >= 0:
            x, y = a[s:], b[: len(b) - s]
        else:
            x, y = a[: len(a) + s], b[-s:]
        if len(x) < 50:
            continue
        x = x - x.mean()
        y = y - y.mean()
        d = np.linalg.norm(x) * np.linalg.norm(y)
        if d == 0:
            continue
        c = float(np.dot(x, y) / d)
        if c > best:
            best, best_shift = c, s
    return (best if best >= 0 else None), best_shift


def classify_coefficient(c: float) -> str:
    """Map a correlation coefficient to a verdict."""
    if c >= SAME_THRESHOLD:
        return VERDICT_SAME
    if c >= PARTIAL_THRESHOLD:
        return VERDICT_PARTIAL
    return VERDICT_DIFFERENT


def compare(a_path: str, b_path: str, win_sec: int = WIN_SEC) -> dict:
    """Compare two media files and return a verdict dict."""
    ea = envelope(a_path, win_sec=win_sec)
    eb = envelope(b_path, win_sec=win_sec)
    c, shift = best_corr(ea, eb)
    return {
        "a": a_path,
        "b": b_path,
        "frames_a": len(ea),
        "frames_b": len(eb),
        "corr": c,
        "shift_frames": shift,
        "shift_sec": round(shift * (1.0 / FRAMES_PER_SEC), 2),
        "verdict": classify_coefficient(c) if c is not None else "unknown",
    }
