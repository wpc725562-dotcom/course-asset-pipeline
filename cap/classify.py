"""Classify a downloaded library into keep / review buckets.

After a batch download you do not have a file problem any more -- you have a
*selection* problem. Which parts are duplicates? Which were marked optional by
the uploader? Which are not teaching content at all? Judging this by memory
does not scale past a handful of courses, so it is done from titles.

Two mechanisms, because titles encode two different kinds of signal:

* **Rule matching** -- uploaders frequently annotate skippable parts right in the
  part title ("(optional)", "legacy version", "intro only", "not in the exam
  syllabus"). Those annotations are high-value and are matched by regex.
* **Variant grouping** -- the same lecture published twice under different
  wording. Titles cannot be compared directly (see ``fingerprint``), so parts
  are grouped by a variant marker and paired by duration.

Rules are **data, not code**: they live in a JSON file so the tool is not tied
to one subject or one exam syllabus. See ``cap/default_rules.json``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# Duration tolerance (minutes) when pairing two variants of the same lecture.
DURATION_TOLERANCE_MIN = 2.0

DEFAULT_RULES_PATH = os.path.join(os.path.dirname(__file__), "default_rules.json")

BUCKETS = ("duplicate", "superseded", "not_exam", "non_teaching", "retract")

BUCKET_LABELS = {
    "duplicate": "content duplicate",
    "superseded": "superseded by a newer version",
    "not_exam": "marked optional / out of scope",
    "non_teaching": "not teaching content",
    "retract": "whole collection withdrawn",
}


def load_rules(path: str | None = None) -> dict:
    """Load classification rules, falling back to the bundled defaults."""
    with open(path or DEFAULT_RULES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class Classification:
    courses: list[dict] = field(default_factory=list)
    buckets: dict[str, list[dict]] = field(default_factory=lambda: {k: [] for k in BUCKETS})

    def totals(self) -> dict[str, dict]:
        out = {}
        for k, items in self.buckets.items():
            out[k] = {"count": len(items), "bytes": sum(i.get("bytes", 0) for i in items)}
        return out


def detect_variant_duplicates(parts: list[dict], variant_re: str,
                              tolerance: float = DURATION_TOLERANCE_MIN) -> tuple[set[int], str | None]:
    """Find parts that are a second upload of another part in the same course.

    Groups parts by whether their title matches ``variant_re``. If both groups
    have the same size and, after sorting by page number, each pair's durations
    agree within ``tolerance`` minutes, the marked group is declared a duplicate.

    Returns ``(page_numbers, explanation)``; an empty set when the check does
    not apply or does not hold.
    """
    marked = [p for p in parts if re.search(variant_re, p["t"])]
    plain = [p for p in parts if not re.search(variant_re, p["t"])]
    if not marked or not plain or len(marked) != len(plain):
        return set(), None

    marked_s = sorted(marked, key=lambda x: x["p"])
    plain_s = sorted(plain, key=lambda x: x["p"])
    if any(abs(a["m"] - b["m"]) > tolerance for a, b in zip(marked_s, plain_s)):
        return set(), None

    return {p["p"] for p in marked}, (
        f"duplicates the primary version (P{plain_s[0]['p']}-P{plain_s[-1]['p']}) "
        f"lecture for lecture; only the upload differs"
    )


def classify_part(title: str, rules: dict) -> tuple[str, str] | None:
    """Return ``(bucket, reason)`` for a part title, or None if it is kept."""
    for pattern, reason in rules.get("non_teaching", []):
        if re.search(pattern, title):
            return "non_teaching", reason
    for pattern, reason in rules.get("not_exam", []):
        if re.search(pattern, title):
            return "not_exam", reason
    for pattern, reason in rules.get("superseded", []):
        if re.search(pattern, title):
            return "superseded", reason
    return None


def run(root: str, survey: list[dict], rules: dict | None = None) -> Classification:
    """Classify every downloaded part of every course under ``root``."""
    rules = rules or load_rules()
    variant_re = rules.get("variant_marker", "(?:字幕版|subbed|subtitled)")
    retract = set(rules.get("retract", []))

    # Discover course directories: <subject>/<course>/
    courses_on_disk: dict[str, dict] = {}
    for subject in sorted(os.listdir(root)):
        sp = os.path.join(root, subject)
        if not os.path.isdir(sp) or subject.startswith("_"):
            continue
        for course in sorted(os.listdir(sp)):
            cp = os.path.join(sp, course)
            if os.path.isdir(cp):
                courses_on_disk[course] = {
                    "path": cp,
                    "rel": f"{subject}/{course}",
                    "subject": subject,
                    "files": [f for f in sorted(os.listdir(cp))
                              if os.path.splitext(f)[1].lower() == ".m4a"],
                }

    from .media import index_by_number

    result = Classification()
    for rec in survey:
        cid = rec.get("bvid", "")
        entry = next((v for k, v in courses_on_disk.items() if cid and cid in k), None)
        if not entry:
            continue

        parts = rec.get("parts", [])
        by_idx = index_by_number(entry["files"])
        dup_pages, dup_reason = detect_variant_duplicates(parts, variant_re)

        for p in parts:
            fname = by_idx.get(p["p"])
            if not fname:
                continue
            full = os.path.join(entry["path"], fname)
            item = {
                "course": rec.get("label", cid),
                "bvid": cid,
                "subject": entry["subject"],
                "p": p["p"],
                "title": p["t"],
                "file": fname,
                "rel": f"{entry['rel']}/{fname}",
                "bytes": os.path.getsize(full) if os.path.exists(full) else 0,
            }

            if cid in retract:
                result.buckets["retract"].append(item)
                continue

            hit = classify_part(p["t"], rules)
            if hit:
                bucket, reason = hit
                result.buckets[bucket].append({**item, "why": reason})
            elif p["p"] in dup_pages:
                result.buckets["duplicate"].append({**item, "why": dup_reason})

        total = sum(
            os.path.getsize(os.path.join(entry["path"], f))
            for f in entry["files"]
            if os.path.exists(os.path.join(entry["path"], f))
        )
        result.courses.append({
            "subject": entry["subject"],
            "label": rec.get("label", cid),
            "owner": rec.get("owner"),
            "bvid": cid,
            "episodes": len(entry["files"]),
            "expected": rec.get("pages"),
            "minutes": rec.get("mins"),
            "bytes": total,
            "dir": entry["rel"],
            "views": (rec.get("stat") or {}).get("view"),
            "danmaku": (rec.get("stat") or {}).get("danmaku"),
            "retract": cid in retract,
        })

    return result
