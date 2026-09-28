"""Tests for targeted re-download."""

from __future__ import annotations

import json

from cap import redownload as rd


def write_manifest(tmp_path, files: list[dict]) -> str:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"root": str(tmp_path), "files": files}), encoding="utf-8")
    return str(p)


def test_collect_bad_returns_only_abnormal_entries(tmp_path):
    manifest = write_manifest(tmp_path, [
        {"rel": "01_math/BV1AAAAAAAAA_alg/001_a.m4a", "status": "ok"},
        {"rel": "01_math/BV1AAAAAAAAA_alg/002_b.m4a", "status": "undecodable"},
    ])
    targets = rd.collect_bad(manifest)
    assert len(targets) == 1
    assert targets[0]["status"] == "undecodable"


def test_collect_bad_extracts_collection_id_from_a_slugged_directory(tmp_path):
    """Course directories are named "<id>_<slug>", so an anchored match fails."""
    manifest = write_manifest(tmp_path, [
        {"rel": "01_math/BV1AAAAAAAAA_linear-algebra/002_b.m4a", "status": "empty"},
    ])
    targets = rd.collect_bad(manifest)
    assert targets[0]["bvid"] == "BV1AAAAAAAAA"


def test_collect_bad_extracts_the_page_number_from_the_prefix(tmp_path):
    manifest = write_manifest(tmp_path, [
        {"rel": "01_math/BV1AAAAAAAAA_c/057_lecture.m4a", "status": "undecodable"},
    ])
    assert rd.collect_bad(manifest)[0]["page"] == 57


def test_collect_bad_preserves_the_original_directory(tmp_path):
    manifest = write_manifest(tmp_path, [
        {"rel": "04_cs/BV1AAAAAAAAA_net/003_x.m4a", "status": "empty"},
    ])
    target = rd.collect_bad(manifest)[0]
    assert target["outdir"] == "04_cs/BV1AAAAAAAAA_net"
    assert target["name"] == "003_x.m4a"


def test_collect_bad_skips_entries_without_a_sequence_prefix(tmp_path):
    manifest = write_manifest(tmp_path, [
        {"rel": "01_math/BV1AAAAAAAAA_c/lecture.m4a", "status": "empty"},
    ])
    assert rd.collect_bad(manifest) == []


def test_collect_bad_skips_entries_at_the_root(tmp_path):
    manifest = write_manifest(tmp_path, [
        {"rel": "001_orphan.m4a", "status": "empty"},
    ])
    assert rd.collect_bad(manifest) == []


def test_collect_bad_on_a_clean_manifest(tmp_path):
    manifest = write_manifest(tmp_path, [
        {"rel": "01_math/BV1AAAAAAAAA_c/001_a.m4a", "status": "ok"},
    ])
    assert rd.collect_bad(manifest) == []


def test_run_on_a_clean_manifest_does_not_shell_out(tmp_path, capsys):
    manifest = write_manifest(tmp_path, [
        {"rel": "01_math/BV1AAAAAAAAA_c/001_a.m4a", "status": "ok"},
    ])
    assert rd.run(manifest, str(tmp_path)) == 0
    assert "nothing to re-download" in capsys.readouterr().out


def test_output_template_uses_autonumber():
    """autonumber == page number; playlist_index yields NA for single videos."""
    assert "%(autonumber)03d" in rd.OUTTMPL
    assert "playlist_index" not in rd.OUTTMPL
