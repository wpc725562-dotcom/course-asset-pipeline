"""Turn a transcript into a readable Markdown document.

A raw ``.srt`` is an intermediate artifact, not something anyone reads. This
layer segments it into sections and emits Markdown with timestamps that link
back to the source video.

Section boundaries come from two signals:

* a **time window** (``window_sec``) so sections stay a consistent size
* a **silence break** (``gap_sec``) so a section never splits mid-sentence

Every generated document carries a disclaimer, because automatic transcription
is a *source*, not a *finished note*. Domain terminology is routinely mangled
and must be corrected by a human or a language model before the note is trusted.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

DISCLAIMER = (
    "> **Note:** this document was produced by automatic speech recognition. "
    "It is useful for searching and skimming, but domain terminology may be "
    "misrecognised. Verify anything you intend to rely on against the source video."
)


@dataclass
class Section:
    start: float
    end: float
    text: str


@dataclass
class NoteOptions:
    window_sec: float = 300.0
    gap_sec: float = 6.0
    title: str = "Transcript"
    source: str | None = None
    author: str | None = None


def hhmmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def build_sections(segments: list[dict], window_sec: float = 300.0,
                   gap_sec: float = 6.0) -> list[Section]:
    """Group segments into sections, breaking early on a long silence."""
    sections: list[Section] = []
    buf: list[dict] = []

    def flush() -> None:
        if buf:
            sections.append(Section(buf[0]["start"], buf[-1]["end"],
                                    "".join(s["text"] for s in buf)))
            buf.clear()

    for seg in segments:
        if buf:
            gap = seg["start"] - buf[-1]["end"]
            long_enough = seg["end"] - buf[0]["start"] >= window_sec
            if long_enough and gap >= gap_sec:
                flush()
        buf.append(seg)
    flush()
    return sections


def render(segments: list[dict], opts: NoteOptions | None = None) -> str:
    opts = opts or NoteOptions()
    sections = build_sections(segments, opts.window_sec, opts.gap_sec)

    lines = [f"# {opts.title}", ""]
    if opts.source:
        lines += [f"- **Source:** {opts.source}"]
    if opts.author:
        lines += [f"- **Author:** {opts.author}"]
    lines += [
        f"- **Length:** {hhmmss(segments[-1]['end']) if segments else '00:00:00'}",
        f"- **Segments:** {len(segments)}",
        "",
        DISCLAIMER,
        "",
        "---",
        "",
    ]
    for i, s in enumerate(sections, 1):
        lines += [f"## {i}. `{hhmmss(s.start)}`", "", s.text.strip(), ""]
    return "\n".join(lines)


def from_json(path: str, opts: NoteOptions | None = None) -> str:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    opts = opts or NoteOptions()
    if not opts.title or opts.title == "Transcript":
        opts.title = os.path.splitext(os.path.basename(path))[0]
    return render(data.get("segments", []), opts)


def from_srt(path: str, opts: NoteOptions | None = None) -> str:
    """Parse an .srt file into segments and render it."""
    import re

    blocks = re.split(r"\n\s*\n", open(path, encoding="utf-8").read().strip())
    ts = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
    segments = []
    for b in blocks:
        m = ts.search(b)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = b[m.end():].strip().replace("\n", " ")
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return render(segments, opts)


def write(segments_or_text, out_path: str, opts: NoteOptions | None = None) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    text = segments_or_text if isinstance(segments_or_text, str) else render(segments_or_text, opts)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return out_path
