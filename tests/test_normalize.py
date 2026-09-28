"""Tests for filename normalization."""

from __future__ import annotations

import json
import os

from cap import normalize as norm


def test_clean_title_replaces_fullwidth_substitutions():
    # yt-dlp --windows-filenames emits these look-alikes for illegal characters.
    assert norm.clean_title("a⧸b：c｜d") == "a-b-c-d"
    assert norm.clean_title("ratio 3：1") == "ratio 3-1"


def test_clean_title_collapses_whitespace_and_trims_dots():
    assert norm.clean_title("  a   b  ") == "a b"
    assert norm.clean_title("...title...") == "title"


def test_truncate_appends_ellipsis_only_when_cut():
    assert norm.truncate("abc", 3) == "abc"
    assert norm.truncate("abcdef", 3) == "abc…"


def test_target_name_pads_the_sequence_number():
    assert norm.target_name(7, "Intro", ".m4a") == "007_Intro.m4a"
    assert norm.target_name(1000, "Intro", ".m4a") == "1000_Intro.m4a"


def test_resolve_is_a_noop_when_already_correct():
    name = "001_Intro.m4a"
    assert norm.resolve(name, {name}, 1, "Intro", ".m4a", 60) == (None, False)


def test_resolve_disambiguates_collisions():
    used = {"001_Intro.m4a", "001_Intro_2.m4a"}
    new_name, collided = norm.resolve("001_Old.m4a", used, 1, "Intro", ".m4a", 60)
    assert new_name == "001_Intro_3.m4a"
    assert collided is True


def test_load_part_titles_skips_errored_records(tmp_path):
    survey = [
        {"bvid": "BV1", "parts": [{"p": 1, "t": "A"}, {"p": 2, "t": "B"}]},
        {"bvid": "BV2", "err": "timeout"},
    ]
    p = tmp_path / "survey.json"
    p.write_text(json.dumps(survey), encoding="utf-8")
    titles = norm.load_part_titles(str(p))
    assert titles == {"BV1": {1: "A", 2: "B"}}


def test_run_mode_b_renames_from_part_titles(tmp_path):
    course = tmp_path / "01_math" / "BV1AAAAAAAAA_linear-algebra"
    course.mkdir(parents=True)
    # Both files share the collection title -- the problem mode B exists to fix.
    (course / "001_Linear algebra full course.m4a").write_bytes(b"x")
    (course / "002_Linear algebra full course.m4a").write_bytes(b"x")

    parts = {"BV1AAAAAAAAA": {1: "Chapter 1 Determinants", 2: "Chapter 2 Matrices"}}
    stats = norm.run(str(tmp_path), parts=parts, dry_run=False)

    assert stats.renamed == 2
    assert sorted(os.listdir(course)) == [
        "001_Chapter 1 Determinants.m4a",
        "002_Chapter 2 Matrices.m4a",
    ]


def test_run_dry_run_changes_nothing(tmp_path):
    course = tmp_path / "01_math" / "BV1AAAAAAAAA_alg"
    course.mkdir(parents=True)
    (course / "001_collection.m4a").write_bytes(b"x")

    parts = {"BV1AAAAAAAAA": {1: "Intro"}}
    stats = norm.run(str(tmp_path), parts=parts, dry_run=True)

    assert stats.renamed == 1
    assert os.listdir(course) == ["001_collection.m4a"]
    assert stats.renames[0]["new"] == "001_Intro.m4a"


def test_run_writes_mapping_for_rollback(tmp_path):
    course = tmp_path / "s" / "BV1AAAAAAAAA_c"
    course.mkdir(parents=True)
    (course / "001_collection.m4a").write_bytes(b"x")
    map_path = tmp_path / "rename_map.json"

    norm.run(str(tmp_path), parts={"BV1AAAAAAAAA": {1: "Intro"}},
             dry_run=True, map_path=str(map_path))

    data = json.loads(map_path.read_text(encoding="utf-8"))
    assert data[0]["old"] == "001_collection.m4a"
    assert data[0]["new"] == "001_Intro.m4a"


def test_run_mode_a_cleans_characters_without_a_survey(tmp_path):
    d = tmp_path / "course"
    d.mkdir()
    (d / "001_a：b.m4a").write_bytes(b"x")

    stats = norm.run(str(tmp_path), parts=None, dry_run=False)
    assert stats.renamed == 1
    assert os.listdir(d) == ["001_a-b.m4a"]


def test_run_reports_parts_without_a_title(tmp_path):
    course = tmp_path / "s" / "BV1AAAAAAAAA_c"
    course.mkdir(parents=True)
    (course / "009_unknown.m4a").write_bytes(b"x")

    stats = norm.run(str(tmp_path), parts={"BV1AAAAAAAAA": {1: "Intro"}}, dry_run=True)
    assert stats.no_title == 1
    assert stats.renamed == 0
