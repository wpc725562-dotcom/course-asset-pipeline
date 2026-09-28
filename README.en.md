# course-asset-pipeline

**Turn a batch of downloaded video courses into a verified, deduplicated, searchable local library.**

A downloader answers "did the file arrive?". This tool answers everything after that: is the file actually intact? Which episodes are two uploads of the same lecture? What can be skipped? And once it is transcribed, how do you actually use it?

---

## The problem

Download 100 episodes of a course and you will hit four failure modes. **None of them raise an error.**

| Symptom | Why naive checks miss it |
|:--|:--|
| File exists, normal size, unplayable | The byte count looks completely reasonable. What is broken is the container header |
| You downloaded 90 episodes; the course has 104 | "Does the file exist?" cannot tell you what is missing |
| The same lecture exists as two uploads | The two versions are **worded completely differently**; string comparison fails |
| You cannot tell which episode is which | The downloader sometimes writes the *collection* title into every file, so N files differ only by a number |

## The pipeline

```
Metadata (Node, API only, seconds)
  cli/bili.mjs survey   part outline + engagement stats  -->  survey.json
  cli/bili.mjs score    quality ranking
  cli/bili.mjs subs     subtitle availability probe

Content (Python)
  yt-dlp               audio download (external)
  cap normalize        restore part titles, fix full-width chars, truncate
  cap verify           count + duration + SHA-256
  cap redownload       re-fetch only what failed, not the whole batch

Organise
  cap classify         duplicate / legacy / optional / non-teaching
  cap fingerprint      audio-level duplicate detection
  cap quarantine       move aside, never delete; one command to undo

Produce
  cap transcribe       speech-to-text (optional extra)
  cap notes            transcript -> Markdown with timestamps
```

## Quick start

```bash
git clone https://github.com/wpc725562-dotcom/course-asset-pipeline
cd course-asset-pipeline
pip install -e ".[dev]"

node cli/bili.mjs survey BV1Aa4y1B7cD --parts --json > survey.json

# ... download audio with yt-dlp ...

cap normalize library --parts survey.json                # dry run
cap normalize library --parts survey.json --apply

cap verify library --expect survey.json
cap redownload library/_manifest/manifest.json --root library
cap verify library --expect survey.json                  # repeat until clean

cap classify survey.json library --out classify.json
cap quarantine classify.json --root library              # dry run
cap quarantine classify.json --root library --apply

cap restore library/_quarantine                          # undo any time
```

## Three design points worth reading

### 1. Verification needs three tiers, because only one of them catches real corruption

"Does it exist?" and "is it zero bytes?" catch almost nothing. The failure that
actually happens is: **normal file size, random content.**

```
healthy: 0000 0024 6674 7970 6973 6f6d   ....ftypisom   valid MP4
corrupt: 650c d2ee 1697 10e3 ad4e 3251   random bytes
```

Searching a corrupt file for `ftyp` / `moov` (mandatory MP4 atoms) finds
**nothing at all** -- so it is not a half-written MP4, the payload is simply not
the target audio. Only opening the container detects it. Hence: count, duration,
and hash.

### 2. Duplicate uploads cannot be detected from titles -- compare the audio

```
P1   Chapter 1 Determinants, part 1 and 2                 [63 min]
P14  [subbed] Chapter 1, both parts                       [63 min]
```

`cap fingerprint` takes a window at the midpoint, decodes to mono PCM, computes a
20 ms RMS energy envelope, and cross-correlates. Two parameters carry all the
weight, and both were wrong the first time:

| Parameter | Value | What went wrong |
|:--|:--|:--|
| Analysis window | **90 s** | A 40 s window has too little structure; unrelated speech correlates at 0.2-0.3 |
| Alignment search | **+/- 25 s** | A 14 s duration difference offsets the midpoint by ~7 s. With +/- 3 s, **the same recording scored 0.2457** and looked unrelated |

Always run a negative control. Measured, after widening the window: **0.9983** for
the same recording, **0.1948** for a different lecture. `tests/test_fingerprint.py`
locks the narrow-window failure in as a regression test.

### 3. Pruning annotates; removal only ever moves

A batch download costs an hour; keeping a redundant file costs a few hundred MB.
That asymmetry makes reversibility the only acceptable default. So `classify`
produces a list, `quarantine` **moves** files into `_quarantine/` while preserving
the hierarchy, writes a machine-readable move log plus human-readable restore
instructions, and then runs a **conservation check**: library + quarantine must
equal the original total.

## Layout

```
cap/                  Python package (media, normalize, verify, redownload,
                      classify, fingerprint, quarantine, transcribe, notes, cli)
cli/bili.mjs          metadata layer (Node, no third-party dependencies)
tests/                88 tests, all offline
scripts/smoke_test.py end-to-end pipeline check with real audio
docs/                 design notes and API notes
SPEC.md               requirements, data model, acceptance criteria
```

## Requirements

- Python >= 3.10 (`numpy`, `av`)
- Node >= 18 (metadata layer only, no third-party dependencies)
- Optional: `faster-whisper` (transcription), `yt-dlp` (download)

## Scope and compliance

- Only public metadata is read; request intervals respect site policy.
- Downloading is for **personal offline study and note-taking**. Do not
  redistribute or use commercially.
- No login checks or access controls are bypassed.
- No course content is bundled. Data under `examples/` is synthetic.

## License

MIT © 2026 wpc725562-dotcom
