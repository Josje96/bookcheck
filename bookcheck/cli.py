"""Command-line entry point for bookcheck.

Typical use (one shot):

    python -m bookcheck.cli run-all manuscript.txt

Or step by step:

    python -m bookcheck.cli ingest  manuscript.txt
    python -m bookcheck.cli extract
    python -m bookcheck.cli check
    python -m bookcheck.cli report
"""

from __future__ import annotations

import argparse
import sys
import time

from . import conflict, extract, ingest, report, resolve, store, summarize, verify
from .ollama_client import OllamaClient, OllamaError

DEFAULT_DB = "data/book.db"
DEFAULT_REPORT = "reports/report.md"


def _read_manuscript(path: str) -> str:
    import os
    if os.path.isdir(path):
        # Folder of chapter files: concatenate in sorted order.
        chunks = []
        for fn in sorted(os.listdir(path)):
            if fn.lower().endswith((".txt", ".md")):
                with open(os.path.join(path, fn), encoding="utf-8") as f:
                    chunks.append(f.read())
        return "\n\n".join(chunks)
    with open(path, encoding="utf-8") as f:
        return f.read()


def cmd_ingest(args):
    conn = store.connect(args.db)
    store.init_db(conn, reset=True)
    text = _read_manuscript(args.manuscript)
    chunks = ingest.split_manuscript(text)
    for c in chunks:
        store.insert_chunk(conn, c)
    conn.commit()
    print(f"Ingested {len(chunks)} scene chunks into {args.db}")
    return conn


def _apply_model_override(args):
    m = getattr(args, "extract_model", None)
    if m:
        extract.EXTRACT_MODEL = m
        conflict.CONSISTENCY_MODEL = m


def cmd_extract(args, conn=None):
    conn = conn or store.connect(args.db)
    _apply_model_override(args)
    client = OllamaClient()
    _require_models(client, [extract.EXTRACT_MODEL])
    print(f"Extraction pass ({extract.EXTRACT_MODEL})...")
    extract.run_extraction(conn, client)
    merged = store.merge_subset_characters(conn)
    if merged:
        print(f"Merged {merged} duplicate character name(s).")
    print("Resolving character aliases...")
    resolve.run_entity_resolution(conn, client)
    print("Extraction complete.")


def cmd_check(args, conn=None):
    conn = conn or store.connect(args.db)
    _apply_model_override(args)
    client = OllamaClient()
    needed = [verify.VERIFY_MODEL]
    if getattr(args, "deep", False):
        needed.append(conflict.FINAL_MODEL)
    _require_models(client, needed)
    print("Entity consistency pass (deterministic stable-attribute check)...")
    n1 = conflict.run_entity_pass(conn, client)
    print(f"  -> {n1} candidate contradiction(s)")
    print(f"Verification pass ({verify.VERIFY_MODEL}) — re-reading sources...")
    kept = verify.run_verification(conn, client)
    print(f"  -> {kept} confirmed after verification")
    # The whole-book "unresolved setup" pass reasons over a lossy digest and
    # produces low-value noise on a single manuscript; opt in with --deep.
    if getattr(args, "deep", False):
        print(f"Final cross-cutting pass ({conflict.FINAL_MODEL})...")
        n2 = conflict.run_final_pass(conn, client)
        print(f"  -> {n2} cross-cutting issue(s)")


def _resolve_wip(args, conn):
    if getattr(args, "finished", False):
        return False
    if getattr(args, "wip", False):
        return True
    detected = store.detect_wip(conn)
    print(f"WIP status: auto-detected as "
          f"{'work-in-progress' if detected else 'finished'} "
          f"(override with --wip / --finished).")
    return detected


def cmd_understand(args, conn=None):
    conn = conn or store.connect(args.db)
    client = OllamaClient()
    _require_models(client, [summarize.SUMMARY_MODEL])
    summarize.run_all_comprehension(conn, client, wip=_resolve_wip(args, conn))


def cmd_report(args, conn=None):
    conn = conn or store.connect(args.db)
    path = report.generate(conn, args.out)
    print(f"Report written to {path}")


def cmd_run_all(args):
    t0 = time.time()
    conn = cmd_ingest(args)
    cmd_extract(args, conn)
    cmd_check(args, conn)
    cmd_understand(args, conn)
    cmd_report(args, conn)
    print(f"\nDone in {time.time() - t0:.0f}s. Open {args.out}")


def _require_models(client: OllamaClient, needed: list[str]):
    try:
        have = client.ensure_up()
    except OllamaError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    missing = [m for m in needed if m not in have]
    if missing:
        print(f"ERROR: missing Ollama models: {missing}. "
              f"Pull with: ollama pull {' && ollama pull '.join(missing)}",
              file=sys.stderr)
        sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="bookcheck",
                                description="Local plot-consistency analyzer.")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite store path")
    p.add_argument("--extract-model", default=None,
                   help="override extraction/entity model (e.g. qwen3:8b)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ingest", help="split manuscript into the store")
    sp.add_argument("manuscript", help="file or folder of .txt/.md chapters")
    sp.set_defaults(func=lambda a: cmd_ingest(a))

    sp = sub.add_parser("extract", help="run extraction pass")
    sp.set_defaults(func=cmd_extract)

    sp = sub.add_parser("check", help="run conflict-detection passes")
    sp.add_argument("--deep", action="store_true",
                    help="also run the whole-book unresolved-setup pass (noisy)")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("understand", help="chapter summaries, character "
                        "descriptions, overall impression")
    sp.add_argument("--wip", action="store_true",
                    help="treat as a work-in-progress (include closing suggestions)")
    sp.add_argument("--finished", action="store_true",
                    help="treat as a finished manuscript (no closing suggestions)")
    sp.set_defaults(func=cmd_understand)

    sp = sub.add_parser("report", help="render markdown report")
    sp.add_argument("--out", default=DEFAULT_REPORT)
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("run-all", help="ingest + extract + check + report")
    sp.add_argument("manuscript", help="file or folder of .txt/.md chapters")
    sp.add_argument("--out", default=DEFAULT_REPORT)
    sp.add_argument("--deep", action="store_true",
                    help="also run the whole-book unresolved-setup pass (noisy)")
    sp.add_argument("--wip", action="store_true",
                    help="treat as a work-in-progress (include closing suggestions)")
    sp.add_argument("--finished", action="store_true",
                    help="treat as a finished manuscript (no closing suggestions)")
    sp.set_defaults(func=cmd_run_all)

    args = p.parse_args(argv)
    # report/run-all need .out present even when called via other paths
    if not hasattr(args, "out"):
        args.out = DEFAULT_REPORT
    args.func(args)


if __name__ == "__main__":
    main()
