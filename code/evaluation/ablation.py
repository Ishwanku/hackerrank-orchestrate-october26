"""Turn off one component at a time and score each variant on the sample set.

    python3 code/evaluation/ablation.py
Prints a Markdown table (copied into evaluation_report.md).
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
from evaluation.score import load, score  # noqa: E402

VARIANTS = [("full system", ""), ("no workflow attribution", "workflow"),
            ("no identity history (audit log)", "history"),
            ("snapshots treated as complete listings", "scope_subjects"),
            ("no pre-request stale-link filter", "stale_filter"),
            ("no PDF/screenshot perception", "perception")]
print("| Variant | Status acc. | Step P | Step R | Step F1 | False-COMPLETE |")
print("| --- | --- | --- | --- | --- | --- |")
for name, flag in VARIANTS:
    out = ROOT / f"code/run/ablate_{flag or 'full'}.csv"
    env = dict(os.environ, GHOST_ABLATE=flag)
    subprocess.run([sys.executable, str(ROOT / "code/main.py"), "--sample", "--out", str(out)],
                   env=env, check=True, capture_output=True)
    m = score(load(out), load(ROOT / "dataset/sample_output.csv"))
    print(f"| {name} | {m['status_accuracy']:.3f} | {m['step_precision']:.3f} | "
          f"{m['step_recall']:.3f} | {m['step_f1']:.3f} | {m['false_complete_rate']:.3f} |")
