"""Independent audit of output.csv, written separately from ghostaudit/validate.py.

    python3 code/evaluation/audit_output.py

Checks the official contract (header, 518 rows, ids/order, statuses, step
numbering, operation order, evidence existence and capture time <= audit_at,
empty evidence on future steps, finding->remediation->verification pairing,
no deletion of retained records) and, from code/run/audit_trail.jsonl when
present (python3 code/main.py --trail), that no observation dated after
audit_at was used and that only unique workflow links exist.
"""
import collections as C
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "dataset"
ORDER = ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK",
         "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD",
         "VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT", "VERIFY_RECORD_REDACTED",
         "VERIFY_RECORD_ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED"]
PH = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
REM2VER = {"DELETE_RECORD": "VERIFY_RECORD_ABSENT", "REDACT_RECORD": "VERIFY_RECORD_REDACTED",
           "ANONYMIZE_RECORD": "VERIFY_RECORD_ANONYMIZED", "DISABLE_DATA_FLOW": "VERIFY_DATA_FLOW_DISABLED",
           "BLOCK_RESTORE": "VERIFY_RESTORE_BLOCKED"}
FIND2REM = {"REPORT_REMAINING_RECORD": "DELETE_RECORD", "REPORT_ACTIVE_DATA_FLOW": "DISABLE_DATA_FLOW",
            "REPORT_RESTORE_RISK": "BLOCK_RESTORE"}


def rd(name):
    with (D / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    with (ROOT / "output.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    hdr, body = rows[0], rows[1:]
    req = {r["case_id"]: r for r in rd("deletion_requests.csv")}
    when = {r["file_id"]: r["captured_at"] for r in rd("evidence_files.csv")}
    when |= {r["activity_id"]: r["event_time"] for r in rd("system_activity.csv")}
    when |= {r["audit_id"]: r["event_time"] for r in rd("user_audit_log.csv")}
    p = []
    if hdr != ["case_id", "deletion_status", "steps_json"]:
        p.append("header")
    if len(body) != 518:
        p.append(f"rows={len(body)}")
    ids = [r[0] for r in body]
    if len(set(ids)) != len(ids) or ids != list(req):
        p.append("ids/order differ from input")
    for cid, st, sj in body:
        s, a = json.loads(sj), req[cid]["audit_at"]
        if st not in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
            p.append(f"{cid} status")
        if st == "NOT_APPLICABLE" and s:
            p.append(f"{cid} NA not empty")
        keys = [(PH[x["phase"]], ORDER.index(x["operation"]), x["system_id"], x["resource_id"]) for x in s]
        if keys != sorted(keys) or [x["step_no"] for x in s] != list(range(1, len(s) + 1)):
            p.append(f"{cid} order/step_no")
        for x in s:
            e = x["evidence_id"]
            if x["phase"] == "FINDING" or st == "COMPLETE":
                if e not in when:
                    p.append(f"{cid} unknown evidence {e}")
                elif when[e] > a:
                    p.append(f"{cid} evidence after audit_at {e}")
            elif e:
                p.append(f"{cid} future step has evidence")
            if x["operation"] == "DELETE_RECORD" and x["resource_id"].split("_")[0] in (
                    "audit", "legal", "tombstone", "backup"):
                p.append(f"{cid} deletes retained {x['resource_id']}")
        if st == "COMPLETE" and any(x["phase"] != "VERIFICATION" for x in s):
            p.append(f"{cid} COMPLETE has non-verification")
        if st == "INCOMPLETE":
            rem = {(x["operation"], x["resource_id"]) for x in s if x["phase"] == "REMEDIATION"}
            ver = {(x["operation"], x["resource_id"]) for x in s if x["phase"] == "VERIFICATION"}
            if not rem or not any(x["phase"] == "FINDING" for x in s):
                p.append(f"{cid} INCOMPLETE missing phase")
            p += [f"{cid} unverified {r}" for o, r in rem if (REM2VER[o], r) not in ver]
            for x in s:
                o = x["operation"]
                if o in FIND2REM and (FIND2REM[o], x["resource_id"]) not in rem:
                    p.append(f"{cid} finding without remediation {x['resource_id']}")
    print("contract problems:", len(p), p[:10])
    tp = ROOT / "code/run/audit_trail.jsonl"
    if tp.exists():
        T = [json.loads(l) for l in tp.open(encoding="utf-8")]
        via = C.Counter(i["via"] for t in T for i in t.get("resources", {}).values())
        late = sum(1 for t in T for i in t.get("resources", {}).values()
                   for h in i.get("history", []) if h.split()[0] > req[t["case_id"]]["audit_at"])
        odd = sum(1 for t in T for rid, i in t.get("resources", {}).items()
                  if i["via"] not in ("evidence", "inferred:workflow-unique")
                  or (i["via"] != "evidence" and not rid.startswith("account_")))
        print("link kinds:", dict(via))
        print("non-unique or non-account workflow links:", odd)
        print("state observations dated after audit_at:", late)
        p += ["late observations"] * bool(late) + ["guessed links"] * bool(odd)
    return 1 if p else 0


if __name__ == "__main__":
    raise SystemExit(main())
