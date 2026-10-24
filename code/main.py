"""Ghost Data Still Exists -- deletion audit agent.

Usage (from the repository root):
    python3 code/main.py                 # audit all requests -> ./output.csv
    python3 code/main.py --sample        # audit sample requests -> code/run/sample_pred.csv
    python3 code/main.py --trail         # also write code/run/audit_trail.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from ghostaudit.ablation import off  # noqa: E402
from ghostaudit.config import OUTPUT_HEADER  # noqa: E402
from ghostaudit.perception.cache import load_perception  # noqa: E402
from ghostaudit.pipeline import Auditor  # noqa: E402
from ghostaudit.validate import validate_rows  # noqa: E402
from ghostaudit.world import load_world  # noqa: E402


def write_csv(path: Path, results) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(OUTPUT_HEADER)
        for r in results:
            w.writerow([r.case_id, r.status, r.steps_json()])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "dataset"))
    ap.add_argument("--sample", action="store_true", help="run on sample requests")
    ap.add_argument("--out", default=None)
    ap.add_argument("--trail", action="store_true", help="write audit trail JSONL")
    ap.add_argument("--cache", default=str(HERE / "cache"),
                    help="perception cache directory (default code/cache)")
    args = ap.parse_args(argv)

    t0 = time.time()
    dataset = Path(args.dataset)
    extra = [] if off("perception") else load_perception(dataset, Path(args.cache))
    world = load_world(dataset, extra_observations=extra)
    auditor = Auditor(world)
    requests = world.sample_requests if args.sample else world.requests
    results = [auditor.audit(r) for r in requests]          # input order = numeric case order
    out = Path(args.out) if args.out else (HERE / "run/sample_pred.csv" if args.sample
                                           else ROOT / "output.csv")
    write_csv(out, results)

    errors = validate_rows(out, requests, world)
    if args.trail:
        trail = HERE / "run" / ("sample_trail.jsonl" if args.sample else "audit_trail.jsonl")
        with trail.open("w", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps({"case_id": r.case_id, "status": r.status, **r.trail},
                                    ensure_ascii=False, sort_keys=True) + "\n")
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print(f"wrote {out} rows={len(results)} {counts} in {time.time() - t0:.2f}s")
    if errors:
        print(f"VALIDATION FAILED: {len(errors)} problem(s)")
        for e in errors[:30]:
            print("  -", e)
        return 1
    print("validation: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
