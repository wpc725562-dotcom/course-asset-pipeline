"""Speech-to-text over downloaded audio, with resumable batch processing.

Three details in here are load-bearing; all three were learned the hard way and
are documented so they are not "cleaned up" later.

**1. Line buffering is mandatory.**
Each subtitle segment is roughly 50 bytes. Python buffers 8 KB by default, so
without ``buffering=1`` the ``.srt`` file stays at 0 bytes for the first ~30% of
a run. That looks exactly like a hang. It is not.

**2. The completion marker must be the ``.json``, never the ``.srt``.**
An interrupted run leaves a non-empty ``.srt`` behind. Using it as the
"already done" marker makes the next run skip a file that was never finished.
The ``.json`` is only written after every segment is flushed.

**3. Never pipe a long transcription into ``tail``/``head``.**
When the downstream pipe closes, the process receives SIGPIPE and dies,
throwing away tens of minutes of work. Redirect to a log file instead.

Note on model size: ``small`` is only good enough for gist. On Chinese technical
speech it mangles domain terms badly, and feeding those terms via
``initial_prompt`` improves segmentation and punctuation but does **not** fix
the terminology. Use ``medium`` for anything whose output will be quoted.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

DEFAULT_MODEL = "small"
DEFAULT_LANGUAGE = "zh"
DEFAULT_BEAM_SIZE = 5


def _srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def completion_marker(outdir: str, base: str) -> str:
    """Path of the file that marks a transcription as finished.

    Deliberately the ``.json`` and not the ``.srt``: an interrupted run leaves a
    non-empty ``.srt`` behind, so treating the ``.srt`` as the marker makes the
    next run skip work that was never completed.
    """
    return os.path.join(outdir, base + ".json")


def is_done(outdir: str, base: str) -> bool:
    return os.path.exists(completion_marker(outdir, base))


@dataclass
class TranscribeOptions:
    model: str = DEFAULT_MODEL
    language: str = DEFAULT_LANGUAGE
    beam_size: int = DEFAULT_BEAM_SIZE
    prompt: str | None = None
    vad_filter: bool = True


def transcribe_file(audio_path: str, outdir: str, opts: TranscribeOptions | None = None,
                    force: bool = False, log=None) -> bool:
    """Transcribe one file into ``<outdir>/<stem>.srt`` and ``.json``."""
    opts = opts or TranscribeOptions()
    log = log or sys.stderr
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(audio_path))[0]
    srt_path = os.path.join(outdir, base + ".srt")
    json_path = completion_marker(outdir, base)

    if is_done(outdir, base) and not force:
        print(f"[skip] {base}", file=log)
        return True

    from faster_whisper import WhisperModel

    model = WhisperModel(opts.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        audio_path,
        language=opts.language,
        beam_size=opts.beam_size,
        vad_filter=opts.vad_filter,
        initial_prompt=opts.prompt,
    )

    rows = []
    # buffering=1 -> line buffered. See module docstring.
    with open(srt_path, "w", encoding="utf-8", buffering=1) as fh:
        for i, seg in enumerate(segments, 1):
            rows.append({"i": i, "start": seg.start, "end": seg.end, "text": seg.text.strip()})
            fh.write(f"{i}\n{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}\n{seg.text.strip()}\n\n")
            if i % 20 == 0:
                print(f"[{base}] {i} segments ...", file=log)

    # Written last, on purpose: this file is the completion marker.
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "source": os.path.abspath(audio_path),
                "model": opts.model,
                "language": info.language,
                "duration": info.duration,
                "segments": rows,
            },
            fh,
            ensure_ascii=False,
            indent=1,
        )
    print(f"[done] {base} ({len(rows)} segments)", file=log)
    return True


def transcribe_dir(audio_dir: str, outdir: str, opts: TranscribeOptions | None = None,
                   force: bool = False, log=None) -> tuple[int, int]:
    """Transcribe every audio file in a directory. Returns (done, skipped)."""
    log = log or sys.stderr
    from .media import MEDIA_EXT

    files = sorted(
        f for f in os.listdir(audio_dir)
        if os.path.splitext(f)[1].lower() in MEDIA_EXT
    )
    done = skipped = 0
    for f in files:
        base = os.path.splitext(f)[0]
        if is_done(outdir, base) and not force:
            skipped += 1
            continue
        transcribe_file(os.path.join(audio_dir, f), outdir, opts, force=force, log=log)
        done += 1
    return done, skipped
