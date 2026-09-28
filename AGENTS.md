# AGENTS.md

Guidance for AI coding agents and human contributors working in this repository.

## What this project is

A pipeline that turns a batch of downloaded video-course files into a verified,
deduplicated, searchable local library. It is deliberately **not** a downloader --
downloading is delegated to `yt-dlp`. Everything here operates on files that
already exist on disk.

## Non-negotiable rules

These encode decisions that were expensive to learn. Do not "simplify" them away.

1. **Verification has three tiers for a reason.** Count alone misses
   corrupt-but-plausible files; duration probing is the only check that catches
   them. Never remove the duration probe or make it optional.
2. **Destructive operations are dry-run by default and reversible when applied.**
   `quarantine` moves files, never deletes. Any new destructive command must
   follow the same pattern and must write a machine-readable undo log.
3. **Always run the conservation check after a prune.** library + quarantine must
   equal the original total. A mismatch means data loss.
4. **Directories starting with `_` are bookkeeping areas** and are excluded from
   all library scans. Adding a new bookkeeping directory means giving it that
   prefix.
5. **The transcription completion marker is the `.json`, never the `.srt`.**
   An interrupted run leaves a non-empty `.srt`.
6. **Never pipe long-running work into `tail`/`head`.** A closed downstream pipe
   raises SIGPIPE and discards the work. Redirect to a log file.
7. **Never use `sys.stdout` / `sys.stderr` as a default argument value.** It binds
   at import time and silently breaks output capture and redirection.
8. **Classification rules live in `cap/default_rules.json`, not in Python.**
   Adding a rule should never require touching code.

## Fingerprint parameters are calibrated, not arbitrary

`cap/fingerprint.py` compares recordings via RMS-envelope cross-correlation.

- `WIN_SEC = 90` -- shorter windows have too little envelope structure; unrelated
  speech correlates at 0.2-0.3 by chance.
- `MAX_SHIFT = 1250` (+/- 25 s) -- two uploads of the same lecture can differ by
  ~14 s in total duration (a trimmed intro), which offsets the midpoint by ~7 s.
  With a +/- 3 s window the *same* recording scores 0.2457 and looks unrelated.

`tests/test_fingerprint.py` asserts the narrow-window failure explicitly. If you
change these constants, that test must still pass -- it is a regression guard, not
a description.

## Testing

```bash
pytest                      # 88 unit tests, offline, < 1 s
python scripts/smoke_test.py  # end-to-end: real audio, real CLI
```

- Unit tests must stay **offline**. Do not add tests that hit the network or
  require large media fixtures. Generate synthetic signals or temp files instead.
- The smoke test is the integration layer. If you change CLI arguments, update it.
- Every acceptance criterion in `SPEC.md` must map to at least one test.

## Style

- Python 3.10+, `from __future__ import annotations`, type hints on public functions.
- Docstrings explain **why**, not what. The code says what.
- Comments that record a non-obvious failure mode are valuable. Keep them.
- Prefer the standard library. Runtime dependencies are `numpy` and `av`; the
  speech-to-text stack is an optional extra.

## Scope boundaries

- Do not add code that bypasses a site's login checks or access controls.
- Do not commit media, generated manifests, or anything under `library/`.
- Do not add content. `examples/` data is synthetic on purpose.

## Commit style

```
feat(verify): probe container headers before hashing

- read duration via PyAV so truncated downloads are detected
- keep SHA-256 as a separate, later step
- SPEC AC1, AC6
```

One commit = one meaningful change. Reference the SPEC AC it implements.
