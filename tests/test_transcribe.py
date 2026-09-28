"""Tests for the transcription layer.

Nothing here loads a speech model -- these cover the resume bookkeeping, which is
where the real bugs were, and they must stay fast enough for CI.
"""

from __future__ import annotations

from cap import transcribe as tr


def test_srt_timestamp_format():
    assert tr._srt_ts(0) == "00:00:00,000"
    assert tr._srt_ts(1.5) == "00:00:01,500"
    assert tr._srt_ts(3661.5) == "01:01:01,500"


def test_srt_timestamp_rounds_to_milliseconds():
    assert tr._srt_ts(0.0004) == "00:00:00,000"
    assert tr._srt_ts(0.0006) == "00:00:00,001"


def test_completion_marker_is_the_json_not_the_srt(tmp_path):
    """An interrupted run leaves a non-empty .srt behind.

    If the .srt were the completion marker, the next run would skip a file that
    was never finished. Only the .json is written after every segment is flushed.
    """
    outdir = str(tmp_path)
    (tmp_path / "a.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\npartial\n",
                                    encoding="utf-8")
    assert tr.completion_marker(outdir, "a").endswith("a.json")
    assert tr.is_done(outdir, "a") is False


def test_is_done_true_when_json_exists(tmp_path):
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    assert tr.is_done(str(tmp_path), "a") is True


def test_transcribe_file_skips_finished_work(tmp_path):
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.json").write_text("{}", encoding="utf-8")

    # Returns before the model is ever constructed.
    assert tr.transcribe_file(str(audio), str(out)) is True


def test_transcribe_dir_skips_finished_files(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    for name in ("a.m4a", "b.m4a"):
        (audio_dir / name).write_bytes(b"x")
        (out / f"{name[:-4]}.json").write_text("{}", encoding="utf-8")

    done, skipped = tr.transcribe_dir(str(audio_dir), str(out))
    assert (done, skipped) == (0, 2)


def test_transcribe_dir_only_considers_media_files(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (audio_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    done, skipped = tr.transcribe_dir(str(audio_dir), str(out))
    assert (done, skipped) == (0, 0)


def test_default_options_are_conservative():
    opts = tr.TranscribeOptions()
    assert opts.model == "small"
    assert opts.beam_size == 5
    assert opts.vad_filter is True
