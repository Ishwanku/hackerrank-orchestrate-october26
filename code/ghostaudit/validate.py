"""Contract validator for output.csv (problem_statement.md + AGENTS.md §6.3-6.6)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .config import OP_PHASE, OP_RANK, OP_STATE, OUTPUT_HEADER, PHASE_RANK, STATUSES
from .models import Request
from .world import World

KEYS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
NEVER_DELETE = {"audit_record", "legal_hold", "tombstone", "backup"}


def validate_rows(path: Path, requests: list[Request], world: World) -> list[str]:
    errs: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if not rows or rows[0] != OUTPUT_HEADER:
        return [f"bad header {rows[:1]}"]
    body = rows[1:]
    want = [r.case_id for r in requests]
    got = [r[0] for r in body]
    if got != want:
        errs.append(f"case ids/order differ from input (got {len(got)}, want {len(want)})")
    audit_at = {r.case_id: r.audit_at for r in requests}
    activity_ids = {c.evidence_id: c.observed_at for c in world.claims}
    audit_ids = {a["audit_id"]: a["event_time"] for a in world.audit_log}
    for row in body:
        if len(row) != 3:
            errs.append(f"{row[:1]}: expected 3 columns")
            continue
        cid, status, raw = row
        if status not in STATUSES:
            errs.append(f"{cid}: bad status {status}")
        try:
            steps = json.loads(raw)
        except json.JSONDecodeError as e:
            errs.append(f"{cid}: steps_json not JSON ({e})")
            continue
        if not isinstance(steps, list):
            errs.append(f"{cid}: steps_json not a list")
            continue
        if status == "NOT_APPLICABLE" and steps != []:
            errs.append(f"{cid}: NOT_APPLICABLE must have []")
        if status == "INCOMPLETE" and steps == []:
            errs.append(f"{cid}: INCOMPLETE with no steps")
        # ponytail: COMPLETE with [] is allowed only when no resource state is visible
        # at audit_at; the audit trail records it and the report lists such cases.
        prev = None
        seen = set()
        for i, s in enumerate(steps, 1):
            if set(s) != KEYS:
                errs.append(f"{cid}#{i}: keys {sorted(s)}")
                continue
            if s["step_no"] != i:
                errs.append(f"{cid}#{i}: step_no {s['step_no']}")
            op = s["operation"]
            if op not in OP_RANK or OP_PHASE[op] != s["phase"] or OP_STATE[op] != s["state"]:
                errs.append(f"{cid}#{i}: illegal triple {s['phase']}/{op}/{s['state']}")
                continue
            k = (PHASE_RANK[s["phase"]], OP_RANK[op], s["system_id"], s["resource_id"])
            if prev and k < prev:
                errs.append(f"{cid}#{i}: out of order")
            prev = k
            if (op, s["resource_id"]) in seen:
                errs.append(f"{cid}#{i}: duplicate {op} {s['resource_id']}")
            seen.add((op, s["resource_id"]))
            ev = s["evidence_id"]
            needs_ev = s["phase"] == "FINDING" or (status == "COMPLETE")
            if needs_ev:
                t = (world.evidence_time(ev) if ev.startswith("evidence_") else
                     activity_ids.get(ev) or audit_ids.get(ev))
                if not ev or t is None:
                    errs.append(f"{cid}#{i}: missing/unknown evidence '{ev}'")
                elif t > audit_at[cid]:
                    errs.append(f"{cid}#{i}: evidence {ev} captured after audit_at")
            elif ev:
                errs.append(f"{cid}#{i}: future step must have empty evidence_id")
            if op == "DELETE_RECORD" and s["resource_id"].rsplit("_", 1)[0] in NEVER_DELETE:
                errs.append(f"{cid}#{i}: deletes a record policy requires to keep")
        phases = {s["phase"] for s in steps if isinstance(s, dict) and "phase" in s}
        if status == "COMPLETE" and phases - {"VERIFICATION"}:
            errs.append(f"{cid}: COMPLETE must contain only verification steps")
        if status == "INCOMPLETE" and not {"FINDING", "REMEDIATION"} <= phases:
            errs.append(f"{cid}: INCOMPLETE needs findings and remediation")
    return errs
