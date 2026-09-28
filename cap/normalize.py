"""Filename normalization for batch-downloaded media.

Three problems this fixes, in increasing severity:

1. **Full-width substitutions.** ``yt-dlp --windows-filenames`` replaces
   characters that are illegal on Windows with look-alike full-width forms
   (``/`` -> ``⧸``, ``:`` -> ``：``, ``|`` -> ``｜``). Titles become ugly and
   unsearchable.

2. **Over-long titles.** A single part title can run to dozens of characters and
   blow past the path length limit.

3. **The filename carries the *collection* title, not the *part* title.**
   yt-dlp's ``%(title)s`` sometimes returns only the parent video title for
   multi-part videos, so all N files of a course share one name and differ only
   by their sequence number -- there is no way to tell which episode is which.
   This behaviour is inconsistent between videos, so it cannot be relied upon.

The fix for (3) is to rename from the part titles recorded in a ``survey.json``
produced by the metadata layer. ``%(autonumber)03d`` equals the part's page
number (1-based), so ``NNN_*.m4a`` maps directly onto ``parts[NNN - 1]``.

The ``NNN_`` prefix is never rewritten: it is both the downloader's
resume/skip key and the lookup key for part titles.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .media import MEDIA_EXT

# yt-dlp full-width substitutions and other characters unsafe in filenames.
CHAR_MAP = {
    "⧸": "-", "／": "-", "/": "-", "\\": "-",
    "：": "-", ":": "-",
    "｜": "-", "|": "-",
    "？": "", "?": "",
    "＊": "x", "*": "x",
    "＜": "", "<": "", "＞": "", ">": "",
    "＂": "", '"': "", "“": "", "”": "",
    "！": "!", "，": ",", "。": ".",
}

NUMBER_PREFIX = re.compile(r"^(\d{1,4})[_\-\s]+(.*)$")


def clean_title(title: str) -> str:
    """Replace unsafe characters and collapse whitespace."""
    for k, v in CHAR_MAP.items():
        title = title.replace(k, v)
    return re.sub(r"\s+", " ", title).strip().strip(" .")


def truncate(title: str, limit: int) -> str:
    """Truncate to ``limit`` characters, appending an ellipsis when cut."""
    if len(title) <= limit:
        return title
    return title[:limit].rstrip(" .-") + "…"


def target_name(idx: int, title: str, ext: str, max_title: int = 60) -> str:
    return f"{idx:03d}_{truncate(clean_title(title), max_title)}{ext}"


def resolve(current: str, used: set[str], idx: int, title: str, ext: str, max_title: int) -> tuple[str | None, bool]:
    """Return ``(new_name, collided)``; ``new_name`` is None when already correct."""
    proposed = target_name(idx, title, ext, max_title)
    if proposed == current:
        return None, False
    candidate, n, collided = proposed, 2, False
    stem, e = os.path.splitext(proposed)
    while candidate in used and candidate != current:
        candidate = f"{stem}_{n}{e}"
        n += 1
        collided = True
    return candidate, collided


@dataclass
class Stats:
    scanned: int = 0
    renamed: int = 0
    already_ok: int = 0
    no_title: int = 0
    collisions: int = 0
    renames: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"scanned {self.scanned}, renamed {self.renamed}, "
            f"already ok {self.already_ok}, no title {self.no_title}, "
            f"collisions resolved {self.collisions}"
        )


def load_part_titles(survey_path: str) -> dict[str, dict[int, str]]:
    """Build ``{collection_id: {page_number: part_title}}`` from a survey file."""
    survey = json.load(open(survey_path, encoding="utf-8"))
    out: dict[str, dict[int, str]] = {}
    for rec in survey:
        if rec.get("err") or not rec.get("parts"):
            continue
        out[rec["bvid"]] = {int(p["p"]): p["t"] for p in rec["parts"] if p.get("t")}
    return out


def run(
    root: str,
    parts: dict[str, dict[int, str]] | None = None,
    dry_run: bool = True,
    max_title: int = 60,
    map_path: str | None = None,
) -> Stats:
    """Normalize filenames under ``root``.

    With ``parts`` given, titles come from the survey (mode B, the recommended
    one). Without it, only character cleanup and renumbering happen (mode A).
    """
    stats = Stats()

    for dirpath, _dirs, files in os.walk(root):
        titles = None
        if parts:
            hits = [b for b in parts if b in dirpath]
            if not hits:
                continue
            titles = parts[hits[0]]

        used = {f for f in files if os.path.splitext(f)[1].lower() in MEDIA_EXT}
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext not in MEDIA_EXT:
                continue
            stats.scanned += 1

            m = NUMBER_PREFIX.match(os.path.splitext(f)[0])
            if not m:
                if titles:
                    stats.no_title += 1
                continue
            idx, rest = int(m.group(1)), m.group(2)

            title = titles.get(idx) if titles else rest
            if not title:
                stats.no_title += 1
                continue

            new_name, collided = resolve(f, used, idx, title, ext, max_title)
            if new_name is None:
                stats.already_ok += 1
                continue
            if collided:
                stats.collisions += 1

            used.discard(f)
            used.add(new_name)
            stats.renames.append({"dir": dirpath, "old": f, "new": new_name})
            stats.renamed += 1
            if not dry_run:
                os.rename(os.path.join(dirpath, f), os.path.join(dirpath, new_name))

    if map_path:
        with open(map_path, "w", encoding="utf-8") as fh:
            json.dump(stats.renames, fh, ensure_ascii=False, indent=1)
    return stats
