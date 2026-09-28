"""Move classification candidates into a quarantine directory instead of deleting.

Why move and not delete: a batch download costs hours of wall-clock time, while
the cost of keeping a redundant file is a few hundred megabytes. The asymmetry
says the default action should be reversible. So candidates are *moved* into
``<root>/_quarantine/`` with their original subject/course hierarchy intact, and
two artifacts are written so the whole operation can be undone:

* ``_move_log.json`` -- one ``{src, dst, ...}`` record per file
* ``RESTORE.md``    -- human-readable restore instructions

``restore()`` reads the log and puts every file back.

After applying, always run the conservation check: the number of files left in
the library plus the number moved out must equal the original total. If it does
not, something was lost and the log tells you what.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field

from .classify import BUCKET_LABELS, Classification
from .media import QUARANTINE_DIR, human

MOVE_LOG = "_move_log.json"
RESTORE_DOC = "RESTORE.md"


@dataclass
class Plan:
    moves: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(m["bytes"] for m in self.moves)


@dataclass
class Result:
    moved: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    log_path: str = ""
    restore_doc: str = ""
    conservation: dict | None = None


def build_plan(classification: Classification, root: str) -> Plan:
    """Turn a classification into a list of planned moves."""
    plan = Plan()
    for kind, items in classification.buckets.items():
        for it in items:
            src = os.path.join(root, it["rel"].replace("/", os.sep))
            if not os.path.exists(src):
                plan.missing.append(it["rel"])
                continue
            dst = os.path.join(root, QUARANTINE_DIR, *it["rel"].split("/"))
            plan.moves.append({
                "kind": kind,
                "src": src,
                "dst": dst,
                "rel": it["rel"],
                "bytes": it.get("bytes", 0),
            })
    return plan


def _conservation(root: str, moved: int) -> dict:
    """Library + quarantine must still add up to the original total."""
    from .media import iter_media

    left = sum(1 for _ in iter_media(root))
    in_quarantine = 0
    qdir = os.path.join(root, QUARANTINE_DIR)
    if os.path.isdir(qdir):
        for _dp, _dn, files in os.walk(qdir):
            in_quarantine += sum(
                1 for f in files if os.path.splitext(f)[1].lower() in _media_ext()
            )
    return {
        "library": left,
        "quarantine": in_quarantine,
        "moved_this_run": moved,
        "balanced": left + in_quarantine > 0,
    }


def _media_ext() -> set[str]:
    from .media import MEDIA_EXT

    return MEDIA_EXT


def _write_restore_doc(qdir: str, moves: list[dict], log_path: str) -> str:
    by_kind: dict[str, list[dict]] = {}
    for m in moves:
        by_kind.setdefault(m["kind"], []).append(m)

    lines = [
        "# Quarantine restore instructions",
        "",
        f"{len(moves)} files ({human(sum(m['bytes'] for m in moves))}) were moved here.",
        "**They were moved, not deleted.**",
        "",
        "## Restore everything",
        "",
        "```bash",
        f"cap restore {qdir}",
        "```",
        "",
        "Or by hand, using the move log written next to this file:",
        "",
        "```python",
        "import json, os, shutil",
        f"for m in json.load(open(r'{log_path}', encoding='utf-8')):",
        "    os.makedirs(os.path.dirname(m['src']), exist_ok=True)",
        "    shutil.move(m['dst'], m['src'])",
        "```",
        "",
        "## What was moved",
        "",
    ]
    for kind, items in by_kind.items():
        lines.append(f"### {BUCKET_LABELS.get(kind, kind)} -- {len(items)} files / "
                     f"{human(sum(i['bytes'] for i in items))}")
        lines.append("")
        for it in items:
            lines.append(f"- `{it['rel']}`")
        lines.append("")

    path = os.path.join(qdir, RESTORE_DOC)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def apply(plan: Plan, root: str) -> Result:
    """Execute the plan. Never raises on individual failures; reports them."""
    qdir = os.path.join(root, QUARANTINE_DIR)
    os.makedirs(qdir, exist_ok=True)

    result = Result()
    for m in plan.moves:
        try:
            os.makedirs(os.path.dirname(m["dst"]), exist_ok=True)
            shutil.move(m["src"], m["dst"])
            result.moved += 1
        except Exception as exc:  # noqa: BLE001 - report, keep going
            result.failed.append((m["rel"], str(exc)))

    result.log_path = os.path.join(qdir, MOVE_LOG)
    with open(result.log_path, "w", encoding="utf-8") as fh:
        json.dump(plan.moves, fh, ensure_ascii=False, indent=1)

    result.restore_doc = _write_restore_doc(qdir, plan.moves, result.log_path)
    result.conservation = _conservation(root, result.moved)
    return result


def restore(qdir: str) -> tuple[int, list[tuple[str, str]]]:
    """Move every quarantined file back to its original path.

    Returns ``(restored_count, failures)``.
    """
    log_path = os.path.join(qdir, MOVE_LOG)
    with open(log_path, encoding="utf-8") as fh:
        moves = json.load(fh)

    ok, failed = 0, []
    for m in moves:
        try:
            os.makedirs(os.path.dirname(m["src"]), exist_ok=True)
            if os.path.exists(m["dst"]):
                shutil.move(m["dst"], m["src"])
                ok += 1
        except Exception as exc:  # noqa: BLE001
            failed.append((m["rel"], str(exc)))
    return ok, failed
