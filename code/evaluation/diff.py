"""Print per-case differences between predictions and the sample reference."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation.score import load, score  # noqa: E402

root = Path(__file__).resolve().parents[2]
res = score(load(root / "code/run/sample_pred.csv"), load(root / "dataset/sample_output.csv"))
trail = {}
tp = root / "code/run/sample_trail.jsonl"
if tp.exists():
    trail = {json.loads(l)["case_id"]: json.loads(l) for l in tp.open()}
for cid, d in res["per_case"].items():
    if d["missing"] or d["extra"] or d["pred"] != d["gold"]:
        print("==", cid, d["pred"], "gold", d["gold"])
        for m in d["missing"]:
            print("   MISSING", m[1], m[3], m[5])
        for e in d["extra"]:
            print("   EXTRA  ", e[1], e[3], e[5])
        if "-v" in sys.argv:
            for rid, info in trail.get(cid, {}).get("resources", {}).items():
                print("     ", rid, {k: v for k, v in info.items() if k != "history"})
                for h in info.get("history", []):
                    print("         ", h)
