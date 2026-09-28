"""Tests for transcript rendering."""

from __future__ import annotations

from cap import notes as nt


def seg(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text}


def test_build_sections_splits_when_window_and_gap_are_both_reached():
    segments = [
        seg(0, 10, "a"),
        seg(10, 20, "b"),
        seg(400, 410, "c"),   # window (300 s) reached and a long pause
    ]
    sections = nt.build_sections(segments, window_sec=300, gap_sec=6)
    assert len(sections) == 2
    assert sections[0].start == 0
    assert sections[1].start == 400


def test_build_sections_keeps_continuous_speech_together():
    """A long section is better than one that splits mid-sentence."""
    segments = [
        seg(0, 10, "a"),
        seg(12, 320, "b"),    # only a 2 s pause -- do not split
        seg(322, 640, "c"),
    ]
    sections = nt.build_sections(segments, window_sec=300, gap_sec=6)
    assert len(sections) == 1


def test_build_sections_does_not_split_on_gap_alone():
    """A pause without enough accumulated content is not a section boundary."""
    segments = [seg(0, 5, "a"), seg(60, 65, "b")]
    sections = nt.build_sections(segments, window_sec=300, gap_sec=6)
    assert len(sections) == 1


def test_build_sections_handles_empty_input():
    assert nt.build_sections([]) == []


def test_hhmmss_pads_to_two_digits():
    assert nt.hhmmss(0) == "00:00:00"
    assert nt.hhmmss(3661) == "01:01:01"
    assert nt.hhmmss(59) == "00:00:59"


def test_render_includes_header_disclaimer_and_timestamps():
    md = nt.render(
        [seg(0, 5, "hello world")],
        nt.NoteOptions(title="Lecture 1", source="https://example.invalid/v/1", author="Someone"),
    )
    assert "# Lecture 1" in md
    assert "https://example.invalid/v/1" in md
    assert "Someone" in md
    # The disclaimer is not optional: automatic transcripts misrecognise terms.
    assert "automatic speech recognition" in md
    assert "`00:00:00`" in md
    assert "hello world" in md


def test_render_numbers_sections():
    segments = [seg(0, 10, "a"), seg(500, 510, "b")]
    md = nt.render(segments, nt.NoteOptions(title="T", window_sec=300, gap_sec=6))
    assert "## 1." in md
    assert "## 2." in md


def test_from_json_uses_the_filename_as_a_default_title(tmp_path):
    p = tmp_path / "lecture-01.json"
    p.write_text('{"segments": [{"start": 0, "end": 1, "text": "hi"}]}', encoding="utf-8")
    md = nt.from_json(str(p))
    assert "# lecture-01" in md


def test_from_srt_parses_blocks(tmp_path):
    srt = tmp_path / "x.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,500\nHello\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nWorld\n",
        encoding="utf-8",
    )
    md = nt.from_srt(str(srt), nt.NoteOptions(title="T"))
    assert "Hello" in md
    assert "World" in md


def test_from_srt_accepts_dot_millisecond_separator(tmp_path):
    srt = tmp_path / "y.srt"
    srt.write_text("1\n00:00:01.000 --> 00:00:03.500\nHello\n", encoding="utf-8")
    md = nt.from_srt(str(srt), nt.NoteOptions(title="T"))
    assert "Hello" in md


def test_write_creates_parent_directories(tmp_path):
    out = tmp_path / "deep" / "nested" / "note.md"
    nt.write([seg(0, 1, "hi")], str(out), nt.NoteOptions(title="T"))
    assert out.exists()
    assert "hi" in out.read_text(encoding="utf-8")
