"""Three-tier integrity verification for a downloaded library.

"Does the file exist?" catches almost nothing. The two failure modes that
actually occur in long batch downloads are:

* **Empty files** -- the download was interrupted before any payload arrived.
* **Files that are present, the right size, and unplayable.** In a large batch,
  a small fraction of downloads can come back as high-entropy garbage: the byte
  count looks normal (megabytes), but the container header is random and there
  is no ``ftyp``/``moov`` atom anywhere in the file. Nothing that only looks at
  existence, count, or size will find these.

So verification runs three independent checks:

===========  ==========================================================
Count        local file count vs. the expected part count from survey
Duration     container-header probe via PyAV, compared to expected length
Hash         SHA-256 per file, archived for later corruption detection
===========  ==========================================================

The duration probe is the one that catches corrupt-but-plausible downloads.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os

from .media import MANIFEST_DIR, human, iter_media, probe_duration, sha256

# Duration tolerance when comparing against the expected length.
DURATION_TOLERANCE = 0.20

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNDECODABLE = "undecodable"


def scan(root: str) -> list[dict]:
    """Walk ``root`` and record size, duration, hash and status per file."""
    root_abs = os.path.abspath(root)
    entries: list[dict] = []
    for full in iter_media(root_abs):
        rel = os.path.relpath(full, root_abs).replace("\\", "/")
        size = os.path.getsize(full)
        dur = probe_duration(full) if size > 0 else None
        if size == 0:
            status = STATUS_EMPTY
        elif dur is None:
            status = STATUS_UNDECODABLE
        else:
            status = STATUS_OK
        entries.append(
            {
                "rel": rel,
                "dir": os.path.dirname(rel),
                "name": os.path.basename(rel),
                "bytes": size,
                "size": human(size),
                "duration_sec": dur,
                "duration_min": round(dur / 60, 1) if dur else None,
                "sha256": sha256(full) if size > 0 else "",
                "status": status,
            }
        )
    return entries


def reconcile(entries: list[dict], survey: list[dict]) -> tuple[list[dict], list[dict]]:
    """Cross-check local counts against expected counts.

    Returns ``(missing, extra)``. A course directory is matched by looking for
    its collection id in the relative directory path.
    """
    by_dir: dict[str, list[dict]] = {}
    for e in entries:
        by_dir.setdefault(e["dir"], []).append(e)

    missing: list[dict] = []
    extra: list[dict] = []
    for rec in survey:
        if rec.get("err"):
            continue
        cid = rec.get("bvid")
        want = rec.get("pages")
        if want is None:
            continue
        matched = [d for d in by_dir if cid and cid in d]
        got = sum(len(by_dir[d]) for d in matched)
        row = {"bvid": cid, "title": rec.get("title", ""), "expected": want, "got": got}
        if got < want:
            missing.append({**row, "missing": want - got})
        elif got > want:
            extra.append(row)
    return missing, extra


def check_durations(entries: list[dict], survey: list[dict]) -> list[dict]:
    """Flag files whose duration deviates from the expected part length.

    Part lengths in a survey are recorded in **minutes**; recorded durations are
    in **seconds**. Convert once, here, so nothing downstream has to remember.
    """
    expected: dict[tuple[str, int], float] = {}
    for rec in survey:
        if rec.get("err"):
            continue
        for p in rec.get("parts", []):
            if p.get("m"):
                expected[(rec["bvid"], int(p["p"]))] = float(p["m"]) * 60.0

    from .media import index_by_number

    by_dir: dict[str, list[dict]] = {}
    for e in entries:
        by_dir.setdefault(e["dir"], []).append(e)

    flagged: list[dict] = []
    for (cid, page), want_sec in expected.items():
        for d, items in by_dir.items():
            if cid not in d:
                continue
            by_idx = index_by_number([i["name"] for i in items])
            name = by_idx.get(page)
            if not name:
                continue
            e = next(i for i in items if i["name"] == name)
            got = e["duration_sec"]
            if got is None:
                continue
            if abs(got - want_sec) > want_sec * DURATION_TOLERANCE:
                flagged.append(
                    {
                        "rel": e["rel"],
                        "expected_sec": round(want_sec, 1),
                        "got_sec": got,
                        "delta_pct": round((got - want_sec) / want_sec * 100, 1),
                    }
                )
    return flagged


def write_manifest(root: str, entries: list[dict], missing: list[dict], extra: list[dict],
                   out_dir: str | None = None) -> dict:
    """Write manifest.json / manifest.csv / checksums.sha256 and return the summary."""
    out_dir = out_dir or os.path.join(root, MANIFEST_DIR)
    os.makedirs(out_dir, exist_ok=True)

    total_bytes = sum(e["bytes"] for e in entries)
    total_dur = sum(e["duration_sec"] or 0 for e in entries)
    bad = [e for e in entries if e["status"] != STATUS_OK]

    summary = {
        "files": len(entries),
        "total_bytes": total_bytes,
        "total_size": human(total_bytes),
        "total_duration_sec": round(total_dur),
        "total_duration_h": round(total_dur / 3600, 2),
        "ok": len(entries) - len(bad),
        "abnormal": len(bad),
        "dirs": len({e["dir"] for e in entries}),
    }

    payload = {
        "root": os.path.abspath(root),
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "missing": missing,
        "extra": extra,
        "abnormal_files": bad,
        "files": entries,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)

    with open(os.path.join(out_dir, "manifest.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rel", "bytes", "size", "duration_sec", "duration_min", "sha256", "status"])
        for e in entries:
            w.writerow([e["rel"], e["bytes"], e["size"], e["duration_sec"],
                        e["duration_min"], e["sha256"], e["status"]])

    with open(os.path.join(out_dir, "checksums.sha256"), "w", encoding="utf-8") as fh:
        for e in entries:
            if e["sha256"]:
                fh.write(f"{e['sha256']}  {e['rel']}\n")

    return summary
