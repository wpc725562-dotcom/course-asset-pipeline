"""Re-download only the files that failed verification.

Why this is a separate command instead of "just run the fetch script again":

After the normalization step, filenames are derived from part titles. The
downloader's skip check compares *filenames*. So re-running the original fetch
script does not skip anything -- it sees every existing file as a mismatch and
re-downloads the entire library.

Instead, read ``manifest.json``, take the entries whose status is not ``ok``,
and for each one derive:

* the collection id, from the course directory name
* the part number, from the ``NNN_`` filename prefix
* the destination path, from the recorded relative path

then re-fetch exactly that part with ``--playlist-items N``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# yt-dlp output template. autonumber == page number, and --no-overwrites makes
# re-runs skip what is already on disk.
OUTTMPL = "%(autonumber)03d_%(title)s.%(ext)s"

DEFAULT_ARGS = [
    "-f", "bestaudio",
    "--no-overwrites",
    "--windows-filenames",
    "--trim-filenames", "80",
    "--sleep-requests", "0.6",
    "--retries", "5",
    "--fragment-retries", "5",
    "--ignore-errors",
    "--no-progress",
]

PREFIX = re.compile(r"^(\d{1,4})[_\-\s]+")


def collect_bad(manifest_path: str) -> list[dict]:
    """Extract re-download targets from a manifest."""
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    targets = []
    for e in manifest.get("files", []):
        if e.get("status") == "ok":
            continue
        rel = e["rel"]
        parts = rel.split("/")
        if len(parts) < 2:
            continue
        course_dir = parts[-2]
        fname = parts[-1]

        m = PREFIX.match(fname)
        if not m:
            continue

        # Collection id: search the whole relative path rather than requiring a
        # path segment to be *exactly* the id. Course directories are usually
        # named "<id>_<slug>", so an anchored match would fail on every one.
        m2 = re.search(r"BV[0-9A-Za-z]{10}", rel)
        cid = m2.group(0) if m2 else course_dir

        targets.append({
            "bvid": cid,
            "page": int(m.group(1)),
            "rel": rel,
            "outdir": os.path.dirname(rel),
            "name": fname,
            "status": e.get("status"),
        })
    return targets


def redownload_one(target: dict, root: str, python_exe: str | None = None,
                   log=None) -> bool:
    """Re-fetch a single part into its original directory."""
    log = log or sys.stdout
    python_exe = python_exe or sys.executable
    outdir = os.path.join(root, target["outdir"].replace("/", os.sep))
    os.makedirs(outdir, exist_ok=True)

    cmd = [
        python_exe, "-m", "yt_dlp",
        *DEFAULT_ARGS,
        "--playlist-items", str(target["page"]),
        "-o", os.path.join(outdir, OUTTMPL),
        f"https://www.bilibili.com/video/{target['bvid']}",
    ]
    print(f"[fetch] {target['rel']}  (page {target['page']})", file=log)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # --ignore-errors makes yt-dlp exit non-zero on partial warnings, so a
        # non-zero code alone is not proof of failure. Re-verification decides.
        print(f"[warn] exit={proc.returncode} for {target['rel']}", file=log)
    return True


def run(manifest_path: str, root: str, python_exe: str | None = None, log=None) -> int:
    # Resolved here rather than as a default argument: a default binds sys.stdout
    # at import time, which defeats output capture (and any later redirection).
    log = log or sys.stdout
    targets = collect_bad(manifest_path)
    if not targets:
        print("[info] no abnormal files in manifest -- nothing to re-download", file=log)
        return 0
    print(f"[info] {len(targets)} file(s) to re-download", file=log)
    for t in targets:
        redownload_one(t, root, python_exe, log)
    print("[info] done. Re-run `cap verify` to confirm.", file=log)
    return 0
