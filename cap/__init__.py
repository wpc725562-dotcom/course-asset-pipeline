"""course-asset-pipeline -- turn a video-course collection into a verified,
deduplicated, searchable local library.

Layers, in the order they run:

===========  ==========================================================
metadata     search, survey part structure, score, detect subtitles
download     yt-dlp audio-only fetch (external)
normalize    repair filenames, restore part titles
verify       count / duration / hash -- three independent checks
redownload   re-fetch only what verification flagged
classify     bucket parts into keep / review
fingerprint  audio-level check for duplicate uploads
quarantine   move review candidates aside, reversibly
transcribe   speech-to-text
notes        transcript -> Markdown
===========  ==========================================================
"""

__version__ = "0.1.0"

__all__ = [
    "classify",
    "cli",
    "fingerprint",
    "media",
    "normalize",
    "notes",
    "quarantine",
    "redownload",
    "transcribe",
    "verify",
]
