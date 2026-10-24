"""Loaders for evidence/records: JSON bundles/exports and the handover text sheet."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from ..models import EvidenceFile, Observation, Scope
from .normalize import record_to_obs

# collection / service-export key -> category refinement
COLLECTION_CATEGORY = {
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "support_conversations": "SUPPORT_MESSAGE",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
    "retained_order_records": "LEGAL_HOLD_RECORD",
    "customer_export_jobs": "USER_EXPORT",
}


def _obs(rec, ef: EvidenceFile, when, where, system=None, category=None, listing=True):
    return record_to_obs(rec, evidence_id=ef.file_id, observed_at=when,
                         source=f"{ef.path}:{where}", system_hint=system,
                         category_hint=category, present_by_listing=listing)


def load_json(ef: EvidenceFile, path: Path) -> tuple[list[Observation], list[Scope]]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    out: list[Observation] = []
    scopes: list[Scope] = []
    top_when = data.get("captured_at") or data.get("exported_at") or ef.captured_at

    def add(o):
        if o is not None:
            out.append(o)

    if "snapshots" in data:                         # records_assurance bundles
        for i, snap in enumerate(data["snapshots"]):
            cat = COLLECTION_CATEGORY.get(snap.get("collection", ""))
            before = len(out)
            for rec in snap.get("records", []):
                add(_obs(rec, ef, snap.get("captured_at"), f"snapshots[{i}]",
                         snap.get("data_store"), cat))
            if snap.get("data_store"):
                scopes.append(Scope(ef.file_id, snap["data_store"], snap.get("captured_at") or top_when,
                                    f"snapshots[{i}]", {o.resource_id for o in out[before:]}))
    elif "service_exports" in data:                 # service_resource_export_*
        for svc, groups in data["service_exports"].items():
            for group, recs in groups.items():
                for rec in recs:
                    add(_obs(rec, ef, rec.get("observed_at") or top_when,
                             f"{svc}.{group}", svc, None))
    elif "records" in data:                         # manifests, ledgers, reports
        cat = COLLECTION_CATEGORY.get(data.get("collection", ""))
        for i, rec in enumerate(data["records"]):
            add(_obs(rec, ef, rec.get("recorded_at") or top_when, f"records[{i}]",
                     None, cat))
    if scopes:
        covered = set().union(*(o.ident_values() for o in out)) if out else set()
        for sc in scopes:
            sc.subjects = covered
    return out, scopes


# "- 2026-10-01T12:00:00Z | account_service | account_146 | USER_PROFILE | NOT_FOUND | e.lindberg18@yahoo.com"
HANDOVER_RE = re.compile(
    r"^-\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(.+?)\s*$")


def load_text(ef: EvidenceFile, path: Path) -> list[Observation]:
    out: list[Observation] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = HANDOVER_RE.match(line.strip())
        if not m:
            continue
        when, system, rid, rtype, result, subject = m.groups()
        rec = {"recorded_at": when, "system": system, "resource_id": rid,
               "record_type": rtype, "result": result,
               "subject_reference": None if subject.lower() == "no direct identifier" else subject}
        o = _obs(rec, ef, when, f"line {n}", system, None, listing=False)
        if o:
            out.append(o)
    return out


def iter_record_files(files: Iterable[EvidenceFile]) -> Iterable[EvidenceFile]:
    return (f for f in files if f.path.startswith("evidence/records/"))
