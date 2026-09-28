"""Tests for library classification."""

from __future__ import annotations

import pytest

from cap import classify as cls


@pytest.fixture()
def rules():
    return cls.load_rules()


def part(page: int, title: str, minutes: float) -> dict:
    return {"p": page, "t": title, "m": minutes}


# --------------------------------------------------------------- variant pairs


def test_variant_duplicates_detected_by_duration_pairing():
    """Titles differ completely; only the duration pairing reveals the duplicate.

    P1  "第一章 行列式 一、概念"            [63 min]
    P14 "【字幕版】第一章 行列式一、二-全"   [63 min]
    """
    parts = [
        part(1, "第一章 行列式 一、概念", 63),
        part(2, "第一章 行列式 二、性质", 55),
        part(14, "【字幕版】第一章 行列式一、二-全", 63),
        part(15, "【字幕版】第一章 行列式三-全", 55),
    ]
    dup, why = cls.detect_variant_duplicates(parts, "字幕版")
    assert dup == {14, 15}
    assert why is not None and "duplicates" in why


def test_variant_pairing_rejected_when_durations_disagree():
    parts = [
        part(1, "A", 63),
        part(2, "B", 55),
        part(14, "【字幕版】A", 40),   # 23 min off -- not the same lecture
        part(15, "【字幕版】B", 55),
    ]
    dup, why = cls.detect_variant_duplicates(parts, "字幕版")
    assert dup == set()
    assert why is None


def test_variant_pairing_rejected_when_counts_differ():
    parts = [
        part(1, "A", 63),
        part(2, "B", 55),
        part(14, "【字幕版】A", 63),
    ]
    dup, why = cls.detect_variant_duplicates(parts, "字幕版")
    assert dup == set()
    assert why is None


def test_variant_pairing_needs_both_groups():
    assert cls.detect_variant_duplicates([part(1, "A", 63)], "字幕版") == (set(), None)


def test_variant_pairing_tolerates_two_minutes(rules):
    tolerance = cls.DURATION_TOLERANCE_MIN
    parts = [
        part(1, "A", 63),
        part(2, "B", 55),
        part(14, "【字幕版】A", 63 + tolerance),
        part(15, "【字幕版】B", 55 + tolerance),
    ]
    dup, _ = cls.detect_variant_duplicates(parts, "字幕版")
    assert dup == {14, 15}


# ------------------------------------------------------------------ rule match


@pytest.mark.parametrize(
    ("title", "bucket"),
    [
        ("导学课", "non_teaching"),
        ("课程介绍", "non_teaching"),
        ("配套教辅在哪里", "non_teaching"),
        ("第三章 （选学）", "not_exam"),
        ("第二章 旧版", "superseded"),
    ],
)
def test_classify_part_rules(title, bucket, rules):
    hit = cls.classify_part(title, rules)
    assert hit is not None
    assert hit[0] == bucket


def test_classify_part_keeps_ordinary_lectures(rules):
    assert cls.classify_part("第一章 极限与连续", rules) is None


def test_rules_are_data_and_can_be_overridden(tmp_path):
    custom = tmp_path / "rules.json"
    custom.write_text(
        '{"variant_marker": "字幕版", "retract": [], "non_teaching": '
        '[["^广告", "advert"]], "not_exam": [], "superseded": []}',
        encoding="utf-8",
    )
    r = cls.load_rules(str(custom))
    assert cls.classify_part("广告时间", r) == ("non_teaching", "advert")
    # The bundled rules would have caught this; the custom set must not.
    assert cls.classify_part("导学课", r) is None


# ------------------------------------------------------------------ end to end


def test_run_builds_courses_and_buckets(tmp_path, rules):
    course = tmp_path / "01_math" / "BV1AAAAAAAAA_linear-algebra"
    course.mkdir(parents=True)
    for name in ["001_Chapter 1.m4a", "002_导学.m4a", "003_Chapter 2 旧版.m4a"]:
        (course / name).write_bytes(b"x")

    survey = [
        {
            "bvid": "BV1AAAAAAAAA",
            "label": "Linear algebra",
            "owner": "Somebody",
            "pages": 3,
            "mins": 100,
            "stat": {"view": 1000, "danmaku": 10},
            "parts": [
                part(1, "Chapter 1 Determinants", 63),
                part(2, "导学", 5),
                part(3, "Chapter 2 旧版", 40),
            ],
        }
    ]

    result = cls.run(str(tmp_path), survey, rules)

    assert len(result.courses) == 1
    assert result.courses[0]["episodes"] == 3
    assert [i["p"] for i in result.buckets["non_teaching"]] == [2]
    assert [i["p"] for i in result.buckets["superseded"]] == [3]
    assert result.buckets["duplicate"] == []


def test_run_honours_retract_list(tmp_path):
    course = tmp_path / "01_math" / "BV1AAAAAAAAA_c"
    course.mkdir(parents=True)
    (course / "001_x.m4a").write_bytes(b"x")

    rules = dict(cls.load_rules())
    rules["retract"] = ["BV1AAAAAAAAA"]
    survey = [{"bvid": "BV1AAAAAAAAA", "label": "c", "pages": 1,
               "parts": [part(1, "Chapter 1", 63)]}]

    result = cls.run(str(tmp_path), survey, rules)
    assert len(result.buckets["retract"]) == 1
    assert result.buckets["non_teaching"] == []


def test_totals_report_bytes(tmp_path, rules):
    course = tmp_path / "01_math" / "BV1AAAAAAAAA_c"
    course.mkdir(parents=True)
    (course / "001_导学.m4a").write_bytes(b"x" * 500)

    survey = [{"bvid": "BV1AAAAAAAAA", "label": "c", "pages": 1,
               "parts": [part(1, "导学", 5)]}]
    result = cls.run(str(tmp_path), survey, rules)
    assert result.totals()["non_teaching"]["bytes"] == 500
