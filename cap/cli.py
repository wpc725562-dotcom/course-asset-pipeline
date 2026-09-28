"""Command-line entry point: ``cap <command> [options]``.

The pipeline is layered, and the commands follow that order:

    metadata  ->  download  ->  normalize  ->  verify  ->  re-download
                                                  |
                                                  v
                            classify  ->  fingerprint  ->  quarantine
                                                  |
                                                  v
                                       transcribe  ->  notes

``cap --help`` lists everything; ``cap <command> --help`` documents one step.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import classify as classify_mod
from . import fingerprint as fp_mod
from . import normalize as norm_mod
from . import notes as notes_mod
from . import quarantine as quarantine_mod
from . import redownload as redownload_mod
from . import transcribe as transcribe_mod
from . import verify as verify_mod
from .media import human


def _cmd_verify(args) -> int:
    if not os.path.isdir(args.root):
        print(f"[fatal] not a directory: {args.root}", file=sys.stderr)
        return 1

    entries = verify_mod.scan(args.root)
    missing, extra = [], []
    if args.expect:
        survey = json.load(open(args.expect, encoding="utf-8"))
        missing, extra = verify_mod.reconcile(entries, survey)
        flagged = verify_mod.check_durations(entries, survey)
        if flagged:
            print(f"\n[!] {len(flagged)} file(s) deviate from the expected duration:")
            for f in flagged[:20]:
                print(f"    {f['rel']}  expected {f['expected_sec']}s, got {f['got_sec']}s "
                      f"({f['delta_pct']:+.1f}%)")

    summary = verify_mod.write_manifest(args.root, entries, missing, extra, args.out)
    bad = [e for e in entries if e["status"] != verify_mod.STATUS_OK]

    print("=" * 68)
    print(f"root         : {os.path.abspath(args.root)}")
    print(f"files        : {summary['files']}")
    print(f"total size   : {summary['total_size']}")
    print(f"total length : {summary['total_duration_h']} h")
    print(f"directories  : {summary['dirs']}")
    print(f"ok / abnormal: {summary['ok']} / {summary['abnormal']}")
    if missing:
        print("\n[!] fewer files than expected:")
        for m in missing:
            print(f"    {m['title'][:34]:36s} expected {m['expected']}, got {m['got']}, "
                  f"missing {m['missing']}")
    if extra:
        print("\n[i] more files than expected:")
        for x in extra:
            print(f"    {x['title'][:34]:36s} expected {x['expected']}, got {x['got']}")
    if bad:
        print("\n[x] abnormal files:")
        for b in bad[:30]:
            print(f"    [{b['status']}] {b['rel']}")
    print("=" * 68)
    print(f"manifest written to {args.out or os.path.join(args.root, verify_mod.MANIFEST_DIR)}")
    return 0 if not bad else 2


def _cmd_normalize(args) -> int:
    parts = norm_mod.load_part_titles(args.parts) if args.parts else None
    dry = not args.apply
    stats = norm_mod.run(args.root, parts=parts, dry_run=dry,
                         max_title=args.max_title, map_path=args.map)
    print(f"[{'dry-run' if dry else 'applied'}] {stats.summary()}", file=sys.stderr)
    if dry and stats.renames:
        for r in stats.renames[:10]:
            print(f"  {r['old']}\n    -> {r['new']}")
        if len(stats.renames) > 10:
            print(f"  ... and {len(stats.renames) - 10} more")
        print("\nNothing was changed. Re-run with --apply to execute.", file=sys.stderr)
    if args.map:
        print(f"[map] {args.map}", file=sys.stderr)
    return 0


def _cmd_classify(args) -> int:
    survey = json.load(open(args.survey, encoding="utf-8"))
    rules = classify_mod.load_rules(args.rules)
    result = classify_mod.run(args.root, survey, rules)

    print(f"courses: {len(result.courses)}")
    for kind, t in result.totals().items():
        print(f"  {kind:14s} {t['count']:4d} files  {human(t['bytes']):>9s}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"root": args.root, "courses": result.courses,
                       "buckets": result.buckets}, fh, ensure_ascii=False, indent=1)
        print(f"[out] {args.out}")
    return 0


def _cmd_quarantine(args) -> int:
    data = json.load(open(args.classify, encoding="utf-8"))
    result = classify_mod.Classification(courses=data.get("courses", []))
    result.buckets = data["buckets"]

    plan = quarantine_mod.build_plan(result, args.root)
    print(f"[info] candidates {sum(len(v) for v in result.buckets.values())}, "
          f"movable {len(plan.moves)}, missing {len(plan.missing)}")
    print(f"[info] would release {human(plan.total_bytes)}")
    for m in plan.missing:
        print(f"  [warn] source not found: {m}")

    if not args.apply:
        for m in plan.moves[:8]:
            print(f"  [dry] {m['rel']}")
        if len(plan.moves) > 8:
            print(f"  ... and {len(plan.moves) - 8} more")
        print("\nNothing was moved. Re-run with --apply to execute.")
        return 0

    res = quarantine_mod.apply(plan, args.root)
    print(f"\n[done] moved {res.moved}, failed {len(res.failed)}")
    for rel, err in res.failed:
        print(f"  x {rel}: {err}")
    print(f"[out] {res.log_path}")
    print(f"[out] {res.restore_doc}")
    if res.conservation:
        c = res.conservation
        print(f"[check] library {c['library']} + quarantine {c['quarantine']} "
              f"(moved this run: {c['moved_this_run']})")
    return 0 if not res.failed else 2


def _cmd_restore(args) -> int:
    ok, failed = quarantine_mod.restore(args.quarantine_dir)
    print(f"[done] restored {ok}, failed {len(failed)}")
    for rel, err in failed:
        print(f"  x {rel}: {err}")
    return 0 if not failed else 2


def _cmd_redownload(args) -> int:
    return redownload_mod.run(args.manifest, args.root)


def _cmd_fingerprint(args) -> int:
    if len(args.files) == 2:
        out = fp_mod.compare(args.files[0], args.files[1], win_sec=args.window)
        print(f"A: {out['a']}")
        print(f"B: {out['b']}")
        print(f"envelope: A={out['frames_a']} frames, B={out['frames_b']} frames (20 ms each)")
        if out["corr"] is None:
            print("cannot compare -- envelope too short")
            return 1
        print(f"\nnormalized cross-correlation = {out['corr']:.4f} "
              f"(best shift {out['shift_frames']} frames = {out['shift_sec']:.2f} s)")
        print(f"verdict: {out['verdict']}")
        return 0

    # Pairwise mode: compare consecutive files listed in a manifest.
    manifest = json.load(open(args.manifest, encoding="utf-8"))
    root = manifest["root"]
    pairs = []
    files = [e for e in manifest["files"] if e["status"] == "ok"]
    for i in range(len(files) - 1):
        a = os.path.join(root, files[i]["rel"].replace("/", os.sep))
        b = os.path.join(root, files[i + 1]["rel"].replace("/", os.sep))
        out = fp_mod.compare(a, b, win_sec=args.window)
        pairs.append(out)
        c = out["corr"]
        print(f"{files[i]['name'][:40]:42s} vs {files[i + 1]['name'][:40]:42s} "
              f"{'n/a' if c is None else f'{c:.4f}'}  {out['verdict']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(pairs, fh, ensure_ascii=False, indent=1)
    return 0


def _cmd_transcribe(args) -> int:
    opts = transcribe_mod.TranscribeOptions(
        model=args.model, language=args.language, beam_size=args.beam_size, prompt=args.prompt
    )
    if os.path.isdir(args.input):
        done, skipped = transcribe_mod.transcribe_dir(args.input, args.out, opts, force=args.force)
        print(f"[done] transcribed {done}, skipped {skipped}")
    else:
        transcribe_mod.transcribe_file(args.input, args.out, opts, force=args.force)
    return 0


def _cmd_notes(args) -> int:
    opts = notes_mod.NoteOptions(title=args.title or "Transcript",
                                 source=args.source, author=args.author,
                                 window_sec=args.window, gap_sec=args.gap)
    if args.input.endswith(".json"):
        text = notes_mod.from_json(args.input, opts)
    else:
        text = notes_mod.from_srt(args.input, opts)
    notes_mod.write(text, args.out)
    print(f"[out] {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cap",
        description="course-asset-pipeline: verify, deduplicate and organise a downloaded video-course library.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("verify", help="three-tier integrity check + manifest")
    v.add_argument("root")
    v.add_argument("--expect", help="survey.json to reconcile counts against")
    v.add_argument("--out", "--out-dir", dest="out", help="manifest output directory")
    v.set_defaults(func=_cmd_verify)

    n = sub.add_parser("normalize", help="normalize filenames (dry-run by default)")
    n.add_argument("root")
    n.add_argument("--parts", help="survey.json providing part titles")
    n.add_argument("--apply", action="store_true", help="actually rename")
    n.add_argument("--max-title", type=int, default=60)
    n.add_argument("--map", help="write old->new mapping JSON")
    n.set_defaults(func=_cmd_normalize)

    c = sub.add_parser("classify", help="bucket parts into keep / review sets")
    c.add_argument("survey")
    c.add_argument("root")
    c.add_argument("--rules", help="rule file (JSON); defaults to the bundled set")
    c.add_argument("--out", help="write classification JSON here")
    c.set_defaults(func=_cmd_classify)

    q = sub.add_parser("quarantine", help="move review candidates into _quarantine (dry-run by default)")
    q.add_argument("classify")
    q.add_argument("--root", required=True)
    q.add_argument("--apply", action="store_true")
    q.set_defaults(func=_cmd_quarantine)

    r = sub.add_parser("restore", help="move quarantined files back")
    r.add_argument("quarantine_dir")
    r.set_defaults(func=_cmd_restore)

    d = sub.add_parser("redownload", help="re-fetch only the files that failed verification")
    d.add_argument("manifest")
    d.add_argument("--root", required=True)
    d.set_defaults(func=_cmd_redownload)

    f = sub.add_parser("fingerprint", help="compare recordings to detect duplicate uploads")
    f.add_argument("files", nargs="*", help="exactly two files for a single comparison")
    f.add_argument("--manifest", help="compare consecutive entries of a manifest instead")
    f.add_argument("--window", type=int, default=fp_mod.WIN_SEC)
    f.add_argument("--out")
    f.set_defaults(func=_cmd_fingerprint)

    t = sub.add_parser("transcribe", help="speech-to-text over audio files")
    t.add_argument("input", help="audio file or directory")
    t.add_argument("out", help="output directory")
    t.add_argument("--model", default=transcribe_mod.DEFAULT_MODEL)
    t.add_argument("--language", default=transcribe_mod.DEFAULT_LANGUAGE)
    t.add_argument("--beam-size", type=int, default=transcribe_mod.DEFAULT_BEAM_SIZE)
    t.add_argument("--prompt", help="domain hint passed to the model")
    t.add_argument("--force", action="store_true", help="re-transcribe finished files")
    t.set_defaults(func=_cmd_transcribe)

    o = sub.add_parser("notes", help="render a transcript as Markdown")
    o.add_argument("input", help=".json transcript or .srt file")
    o.add_argument("out")
    o.add_argument("--title")
    o.add_argument("--source")
    o.add_argument("--author")
    o.add_argument("--window", type=float, default=300.0)
    o.add_argument("--gap", type=float, default=6.0)
    o.set_defaults(func=_cmd_notes)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
