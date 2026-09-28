"""Shared helpers: media extensions, size formatting, hashing, duration probing.

Everything in this module is dependency-light on purpose so that the pure-logic
layers (normalize / classify / quarantine) stay testable without decoding audio.
"""

from __future__ import annotations

import hashlib
import os
from typing import Iterator

# Audio and video containers we treat as "library assets".
MEDIA_EXT = {
    ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus",
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
}

# Directories starting with this prefix are bookkeeping areas (manifests,
# quarantine) and are excluded from library-wide scans.
BOOKKEEPING_PREFIX = "_"

MANIFEST_DIR = "_manifest"
QUARANTINE_DIR = "_quarantine"


def human(n: float) -> str:
    """Format a byte count as a short human-readable string."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def sha256(path: str, chunk: int = 1 << 20) -> str:
    """Stream a file through SHA-256. Returns "" for unreadable/empty files."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return ""
    return h.hexdigest()


def probe_duration(path: str) -> float | None:
    """Return media duration in seconds, or None if the container is unreadable.

    This is the single most valuable check in the pipeline: a truncated or
    corrupted download usually still has a plausible file size, so size alone
    cannot detect it. Opening the container can.
    """
    try:
        import av

        with av.open(path) as c:
            if c.duration is not None:
                return round(c.duration / av.time_base, 1)
            # Fallback for containers without a duration header: last packet PTS.
            last = 0
            for stream in c.streams.audio:
                for pkt in c.demux(stream):
                    if pkt.pts is not None:
                        last = pkt.pts
            return round(last / av.time_base, 1) if last else None
    except Exception:
        return None


def is_media(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in MEDIA_EXT


def is_bookkeeping(rel_dir: str) -> bool:
    """True if any path segment of rel_dir starts with ``_``."""
    return any(part.startswith(BOOKKEEPING_PREFIX) for part in rel_dir.split(os.sep))


def iter_media(root: str, skip_bookkeeping: bool = True) -> Iterator[str]:
    """Yield absolute paths of media files under ``root``.

    ``skip_bookkeeping`` excludes ``_manifest`` / ``_quarantine`` and anything
    else underscore-prefixed. Without this, post-quarantine statistics are
    inflated by the quarantined files themselves.
    """
    root_abs = os.path.abspath(root)
    for dirpath, dirs, files in os.walk(root_abs):
        if skip_bookkeeping:
            rel_dir = os.path.relpath(dirpath, root_abs)
            if is_bookkeeping(rel_dir):
                dirs[:] = []
                continue
        for f in sorted(files):
            if is_media(f):
                yield os.path.join(dirpath, f)


def index_by_number(files: list[str]) -> dict[int, str]:
    """Map ``NNN_...`` filename prefixes to filenames.

    ``NNN`` comes from yt-dlp's ``%(autonumber)03d``, which equals the playlist
    page number. Failed downloads do **not** shift the numbering, because
    autonumber counts entries rather than successes.
    """
    import re

    out: dict[int, str] = {}
    for f in files:
        m = re.match(r"^(\d{1,4})[_\-\s]+", f)
        if m:
            out[int(m.group(1))] = f
    return out
