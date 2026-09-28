"""Tests for integrity verification."""

from __future__ import annotations

import json

from cap import verify as vf


def entry(rel: str, size: int = 10, status: str = "ok") -> dict:
    return {
        "rel": rel,
        "dir": rel.rsplit("/", 1)[0] if "/" in rel else "",
        "name": rel.rsplit("/", 1)[-1],
        "bytes": size,
        "size": f"{size}B",
        "duration_sec": 5.0,
        "duration_min": 0.1,
        "sha256": "deadbeef",
        "status": status,
    }


# ------------------------------------------------------------------- scanning


def test_scan_flags_empty_files(tmp_path):
    (tmp_path / "empty.m4a").write_bytes(b"")
    entries = vf.scan(str(tmp_path))
    assert [e["status"] for e in entries] == [vf.STATUS_EMPTY]


def test_scan_flags_files_that_cannot_be_decoded(tmp_path):
    """The failure mode that size checks miss: present, plausible size, garbage.

    A real corrupted download looks like this -- megabytes of high-entropy bytes
    with no readable container header.
    """
    (tmp_path / "broken.m4a").write_bytes(b"not a container at all")
    entries = vf.scan(str(tmp_path))
    assert entries[0]["status"] == vf.STATUS_UNDECODABLE
    assert entries[0]["bytes"] > 0


def test_scan_skips_bookkeeping_directories(tmp_path):
    """Quarantined and manifest files must not inflate post-prune statistics."""
    for sub in ("_quarantine/01_math", "_manifest"):
        d = tmp_path / sub
        d.mkdir(parents=True)
        (d / "x.m4a").write_bytes(b"z")
    (tmp_path / "keep.m4a").write_bytes(b"z")

    names = {e["name"] for e in vf.scan(str(tmp_path))}
    assert names == {"keep.m4a"}


def test_scan_records_a_hash_for_each_file(tmp_path):
    (tmp_path / "a.m4a").write_bytes(b"payload")
    e = vf.scan(str(tmp_path))[0]
    assert len(e["sha256"]) == 64


# ---------------------------------------------------------------- reconciling


def test_reconcile_reports_missing_and_extra():
    entries = [
        entry("01_math/BV1AAAA_alg/001_a.m4a"),
        entry("01_math/BV1AAAA_alg/002_a.m4a"),
        entry("01_math/BV2BBBB_calc/001_b.m4a"),
        entry("01_math/BV2BBBB_calc/002_b.m4a"),
        entry("01_math/BV2BBBB_calc/003_b.m4a"),
    ]
    survey = [
        {"bvid": "BV1AAAA", "title": "algebra", "pages": 5},
        {"bvid": "BV2BBBB", "title": "calculus", "pages": 2},
    ]
    missing, extra = vf.reconcile(entries, survey)

    assert missing[0]["bvid"] == "BV1AAAA"
    assert missing[0]["missing"] == 3
    assert extra[0]["bvid"] == "BV2BBBB"
    assert extra[0]["got"] == 3


def test_reconcile_ignores_errored_survey_records():
    entries = [entry("d/BV1AAAA_x/001_a.m4a")]
    survey = [{"bvid": "BV1AAAA", "err": "timeout"}]
    assert vf.reconcile(entries, survey) == ([], [])


def test_reconcile_ignores_records_without_an_expected_count():
    entries = [entry("d/BV1AAAA_x/001_a.m4a")]
    assert vf.reconcile(entries, [{"bvid": "BV1AAAA", "title": "x"}]) == ([], [])


# ------------------------------------------------------------ duration checks


def test_check_durations_flags_deviation(tmp_path):
    entries = [entry("d/BV1AAAA_x/001_a.m4a")]
    entries[0]["duration_sec"] = 2000.0        # expected 3600 s -> -44%
    survey = [{
        "bvid": "BV1AAAA",
        "parts": [{"p": 1, "t": "A", "m": 60}],   # 60 minutes
    }]
    flagged = vf.check_durations(entries, survey)
    assert len(flagged) == 1
    assert flagged[0]["delta_pct"] < 0


def test_check_durations_accepts_within_tolerance():
    entries = [entry("d/BV1AAAA_x/001_a.m4a")]
    entries[0]["duration_sec"] = 3600 * 1.1     # +10%, tolerance is 20%
    survey = [{"bvid": "BV1AAAA", "parts": [{"p": 1, "t": "A", "m": 60}]}]
    assert vf.check_durations(entries, survey) == []


# ------------------------------------------------------------------- manifest


def test_write_manifest_emits_three_artifacts(tmp_path):
    out = tmp_path / "_manifest"
    summary = vf.write_manifest(str(tmp_path), [entry("a.m4a")], [], [], str(out))

    assert summary["files"] == 1
    assert summary["abnormal"] == 0
    assert (out / "manifest.json").exists()
    assert (out / "manifest.csv").exists()
    assert (out / "checksums.sha256").read_text(encoding="utf-8").strip() == "deadbeef  a.m4a"


def test_write_manifest_summarises_abnormal_files(tmp_path):
    out = tmp_path / "_manifest"
    entries = [entry("a.m4a"), entry("b.m4a", status=vf.STATUS_UNDECODABLE)]
    summary = vf.write_manifest(str(tmp_path), entries, [], [], str(out))

    assert summary["ok"] == 1
    assert summary["abnormal"] == 1

    payload = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert payload["abnormal_files"][0]["rel"] == "b.m4a"
