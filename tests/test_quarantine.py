"""Tests for reversible quarantine."""

from __future__ import annotations

import json
import os

from cap import classify as cls
from cap import quarantine as q


def make_library(tmp_path):
    course = tmp_path / "01_math" / "BV1AAAAAAAAA_alg"
    course.mkdir(parents=True)
    (course / "001_keep.m4a").write_bytes(b"x" * 100)
    (course / "002_review.m4a").write_bytes(b"x" * 200)
    return course


def classification_for(rel: str, bucket: str = "superseded") -> cls.Classification:
    c = cls.Classification()
    c.buckets[bucket].append({"rel": rel, "bytes": 200})
    return c


def test_build_plan_maps_relative_paths_to_moves(tmp_path):
    make_library(tmp_path)
    plan = q.build_plan(
        classification_for("01_math/BV1AAAAAAAAA_alg/002_review.m4a"), str(tmp_path)
    )
    assert len(plan.moves) == 1
    assert plan.moves[0]["dst"] == os.path.join(
        str(tmp_path), "_quarantine", "01_math", "BV1AAAAAAAAA_alg", "002_review.m4a"
    )
    assert plan.total_bytes == 200


def test_build_plan_records_missing_sources(tmp_path):
    plan = q.build_plan(classification_for("01_math/nope/ghost.m4a"), str(tmp_path))
    assert plan.moves == []
    assert plan.missing == ["01_math/nope/ghost.m4a"]


def test_apply_moves_rather_than_deletes(tmp_path):
    course = make_library(tmp_path)
    plan = q.build_plan(
        classification_for("01_math/BV1AAAAAAAAA_alg/002_review.m4a"), str(tmp_path)
    )
    result = q.apply(plan, str(tmp_path))

    assert result.moved == 1
    assert not (course / "002_review.m4a").exists()
    quarantined = tmp_path / "_quarantine" / "01_math" / "BV1AAAAAAAAA_alg" / "002_review.m4a"
    assert quarantined.exists()
    assert quarantined.stat().st_size == 200


def test_apply_preserves_the_directory_hierarchy(tmp_path):
    make_library(tmp_path)
    plan = q.build_plan(
        classification_for("01_math/BV1AAAAAAAAA_alg/002_review.m4a"), str(tmp_path)
    )
    q.apply(plan, str(tmp_path))
    # Subject / course / file -- so a restore is a plain move back.
    assert (tmp_path / "_quarantine" / "01_math" / "BV1AAAAAAAAA_alg").is_dir()


def test_apply_writes_a_move_log(tmp_path):
    make_library(tmp_path)
    plan = q.build_plan(
        classification_for("01_math/BV1AAAAAAAAA_alg/002_review.m4a"), str(tmp_path)
    )
    result = q.apply(plan, str(tmp_path))

    moves = json.loads(open(result.log_path, encoding="utf-8").read())
    assert moves[0]["rel"] == "01_math/BV1AAAAAAAAA_alg/002_review.m4a"
    assert os.path.exists(moves[0]["dst"])


def test_apply_writes_restore_instructions(tmp_path):
    make_library(tmp_path)
    plan = q.build_plan(
        classification_for("01_math/BV1AAAAAAAAA_alg/002_review.m4a"), str(tmp_path)
    )
    result = q.apply(plan, str(tmp_path))

    doc = open(result.restore_doc, encoding="utf-8").read()
    assert "moved, not deleted" in doc
    assert "cap restore" in doc
    assert "002_review.m4a" in doc


def test_conservation_check_balances(tmp_path):
    """library + quarantine must still add up after the move."""
    make_library(tmp_path)
    plan = q.build_plan(
        classification_for("01_math/BV1AAAAAAAAA_alg/002_review.m4a"), str(tmp_path)
    )
    result = q.apply(plan, str(tmp_path))

    assert result.conservation["library"] == 1
    assert result.conservation["quarantine"] == 1
    assert result.conservation["moved_this_run"] == 1


def test_restore_round_trip(tmp_path):
    course = make_library(tmp_path)
    original = (course / "002_review.m4a").read_bytes()

    plan = q.build_plan(
        classification_for("01_math/BV1AAAAAAAAA_alg/002_review.m4a"), str(tmp_path)
    )
    q.apply(plan, str(tmp_path))

    restored, failed = q.restore(str(tmp_path / "_quarantine"))

    assert restored == 1
    assert failed == []
    assert (course / "002_review.m4a").read_bytes() == original


def test_apply_reports_failures_without_raising(tmp_path):
    make_library(tmp_path)
    plan = q.build_plan(
        classification_for("01_math/BV1AAAAAAAAA_alg/002_review.m4a"), str(tmp_path)
    )
    # Sabotage: remove the source between planning and applying.
    os.remove(plan.moves[0]["src"])

    result = q.apply(plan, str(tmp_path))
    assert result.moved == 0
    assert len(result.failed) == 1
