#!/usr/bin/env python
"""End-to-end smoke test: build a synthetic library and run the whole pipeline.

The unit tests cover each layer in isolation with fakes. This script does the
opposite -- it generates *real* (tiny) AAC files and drives the actual CLI, so it
catches integration problems that unit tests cannot see: path handling, the
conservation check, and the quarantine/restore round trip.

Run it directly, or via CI:

    python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

import av
import numpy as np

# Running this file directly puts scripts/ on sys.path, not the repo root, so the
# cap package would not be importable. Add the root explicitly.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

RATE = 16000

# (relative path, seconds, tone frequency)
FILES = [
    ("01_math/BV1AAAAAAAAA_linear-algebra/001_Chapter 1 Determinants.m4a", 3, 220),
    ("01_math/BV1AAAAAAAAA_linear-algebra/002_导学.m4a", 3, 300),
    ("01_math/BV1AAAAAAAAA_linear-algebra/003_Chapter 2 Matrices 旧版.m4a", 3, 180),
    ("02_cs/BV2BBBBBBBBB_data-structures/001_Lecture 1 Arrays.m4a", 3, 260),
    ("02_cs/BV2BBBBBBBBB_data-structures/002_Lecture 2 Lists.m4a", 3, 340),
]

SURVEY = [
    {
        "bvid": "BV1AAAAAAAAA",
        "label": "Linear algebra",
        "owner": "Demo Channel",
        "pages": 3,
        "mins": 9,
        "stat": {"view": 12000, "danmaku": 40},
        "parts": [
            {"p": 1, "t": "Chapter 1 Determinants", "m": 3},
            {"p": 2, "t": "导学", "m": 3},
            {"p": 3, "t": "Chapter 2 Matrices 旧版", "m": 3},
        ],
    },
    {
        "bvid": "BV2BBBBBBBBB",
        "label": "Data structures",
        "owner": "Demo Channel",
        "pages": 2,
        "mins": 6,
        "stat": {"view": 9000, "danmaku": 12},
        "parts": [
            {"p": 1, "t": "Lecture 1 Arrays", "m": 3},
            {"p": 2, "t": "Lecture 2 Lists", "m": 3},
        ],
    },
]

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)


def make_audio(path: str, seconds: int, freq: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t = np.arange(int(RATE * seconds)) / RATE
    signal = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    with av.open(path, "w", format="ipod") as container:
        stream = container.add_stream("aac", rate=RATE)
        stream.layout = "mono"
        for i in range(0, len(signal), 1024):
            frame = av.AudioFrame.from_ndarray(
                signal[i:i + 1024].reshape(1, -1), format="fltp", layout="mono"
            )
            frame.rate = RATE
            container.mux(stream.encode(frame))
        container.mux(stream.encode(None))


def run(*args: str) -> str:
    """Invoke the CLI in a subprocess and return its stdout."""
    proc = subprocess.run(
        [sys.executable, "-m", "cap.cli", *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if proc.returncode not in (0, 2):  # 2 == "abnormal files found", still valid
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(args)}")
    return proc.stdout + proc.stderr


def main() -> int:
    root = tempfile.mkdtemp(prefix="cap-smoke-")
    try:
        print(f"[setup] building a synthetic library in {root}")
        for rel, secs, freq in FILES:
            make_audio(os.path.join(root, rel.replace("/", os.sep)), secs, freq)
        survey_path = os.path.join(root, "survey.json")
        with open(survey_path, "w", encoding="utf-8") as fh:
            json.dump(SURVEY, fh, ensure_ascii=False, indent=1)

        print("\n[1] cap verify")
        out = run("verify", root, "--expect", survey_path)
        check("ok / abnormal: 5 / 0" in out, "verify reports 5 healthy files")
        check("files        : 5" in out, "verify counts 5 files")
        manifest_path = os.path.join(root, "_manifest", "manifest.json")
        check(os.path.exists(manifest_path), "manifest.json written")
        check(os.path.exists(os.path.join(root, "_manifest", "checksums.sha256")),
              "checksums.sha256 written")

        print("\n[2] cap classify")
        classify_path = os.path.join(root, "classify.json")
        out = run("classify", survey_path, root, "--out", classify_path)
        check("courses: 2" in out, "classify finds 2 courses")
        data = json.load(open(classify_path, encoding="utf-8"))
        check(len(data["buckets"]["non_teaching"]) == 1, "orientation flagged as non-teaching")
        check(len(data["buckets"]["superseded"]) == 1, "legacy version flagged as superseded")

        print("\n[3] cap quarantine (dry run)")
        out = run("quarantine", classify_path, "--root", root)
        check("movable 2" in out, "2 candidates are movable")
        check("Nothing was moved" in out, "dry run moves nothing")
        check(not os.path.exists(os.path.join(root, "_quarantine")),
              "no quarantine directory created yet")

        print("\n[4] cap quarantine --apply")
        out = run("quarantine", classify_path, "--root", root, "--apply")
        check("moved 2" in out, "2 files moved")
        check("library 3 + quarantine 2" in out, "conservation check balances (3 + 2 = 5)")
        check(os.path.exists(os.path.join(root, "_quarantine", "_move_log.json")),
              "_move_log.json written")
        check(os.path.exists(os.path.join(root, "_quarantine", "RESTORE.md")),
              "RESTORE.md written")

        print("\n[5] verify skips bookkeeping directories")
        out = run("verify", root, "--expect", survey_path)
        check("files        : 3" in out, "verify now counts only the 3 kept files")

        print("\n[6] cap restore")
        out = run("restore", os.path.join(root, "_quarantine"))
        check("restored 2" in out, "2 files restored")
        out = run("verify", root, "--expect", survey_path)
        check("files        : 5" in out, "library is whole again")

        print("\n[7] manifest-driven re-download target selection")
        from cap import redownload as rd

        manifest = json.load(open(manifest_path, encoding="utf-8"))
        manifest["files"][0]["status"] = "undecodable"
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False)
        targets = rd.collect_bad(manifest_path)
        check(len(targets) == 1, "exactly one re-download target")
        check(targets[0]["page"] == 1, "page number read from the filename prefix")
        check(targets[0]["bvid"] == "BV1AAAAAAAAA", "collection id read from the directory")

    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    if failures:
        print(f"SMOKE TEST FAILED -- {len(failures)} check(s) did not pass:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SMOKE TEST PASSED -- full pipeline verified end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
