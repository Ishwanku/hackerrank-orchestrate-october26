"""Score predictions against reference answers (sample_output.csv by default).

Metrics
- status accuracy: deletion_status exact match per case
- exact case match: whole steps_json array identical
- step precision / recall / F1 on full step tuples (ignores step_no)
- field accuracy: for steps matched on (phase, operation, system_id, resource_id),
  share whose state and evidence_id also match
- sequence accuracy: among cases whose predicted step *set* equals the
  reference set, share in identical order
- false-COMPLETE rate: predicted COMPLETE where reference is INCOMPLETE
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


def load(path: Path) -> dict[str, tuple[str, list[dict]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"]))
                for r in csv.DictReader(fh)}


def key(s: dict, full: bool = True) -> tuple:
    base = (s["phase"], s["operation"], s["system_id"], s["resource_id"])
    return base + ((s["state"], s["evidence_id"]) if full else ())


def score(pred: dict, gold: dict) -> dict:
    m = Counter()
    per_case = {}
    for cid, (gs, gsteps) in gold.items():
        ps, psteps = pred.get(cid, ("MISSING", []))
        m["cases"] += 1
        m["status_ok"] += ps == gs
        m["exact"] += (ps == gs and [key(s) for s in psteps] == [key(s) for s in gsteps])
        gk, pk = Counter(key(s) for s in gsteps), Counter(key(s) for s in psteps)
        tp = sum((gk & pk).values())
        m["tp"] += tp
        m["fp"] += sum(pk.values()) - tp
        m["fn"] += sum(gk.values()) - tp
        gb = {key(s, False): s for s in gsteps}
        for s in psteps:
            g = gb.get(key(s, False))
            if g:
                m["matched"] += 1
                m["state_ok"] += s["state"] == g["state"]
                m["evidence_ok"] += s["evidence_id"] == g["evidence_id"]
        if set(gk) == set(pk) and gk:
            m["same_set"] += 1
            m["same_order"] += [key(s) for s in psteps] == [key(s) for s in gsteps]
        if ps == "COMPLETE" and gs == "INCOMPLETE":
            m["false_complete"] += 1
        m["gold_incomplete"] += gs == "INCOMPLETE"
        per_case[cid] = {"pred": ps, "gold": gs,
                         "missing": sorted(set(gk) - set(pk)), "extra": sorted(set(pk) - set(gk))}
    p = m["tp"] / max(1, m["tp"] + m["fp"])
    r = m["tp"] / max(1, m["tp"] + m["fn"])
    return {
        "cases": m["cases"],
        "status_accuracy": m["status_ok"] / m["cases"],
        "exact_case_match": m["exact"] / m["cases"],
        "step_precision": p, "step_recall": r,
        "step_f1": 2 * p * r / max(1e-9, p + r),
        "state_accuracy_on_matched": m["state_ok"] / max(1, m["matched"]),
        "evidence_accuracy_on_matched": m["evidence_ok"] / max(1, m["matched"]),
        "sequence_accuracy": m["same_order"] / max(1, m["same_set"]),
        "false_complete_rate": m["false_complete"] / max(1, m["gold_incomplete"]),
        "per_case": per_case,
    }


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[2]
    pred = load(Path(sys.argv[1]) if len(sys.argv) > 1 else root / "code/run/sample_pred.csv")
    gold = load(root / "dataset/sample_output.csv")
    res = score(pred, gold)
    for k, v in res.items():
        if k != "per_case":
            print(f"{k:32s} {v:.3f}" if isinstance(v, float) else f"{k:32s} {v}")
