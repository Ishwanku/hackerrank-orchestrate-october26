"""Loader for evidence/databases/*.sql point-in-time snapshots.

Each file is executed in an in-memory SQLite database (the files are
SQLite-compatible by contract). Two layouts exist:

* inventory captures: one table per data store plus ``snapshot_scope``, which
  states which origin systems were captured and when. A resource of an
  in-scope system that is *missing* from its table was absent at that time.
* topology captures: ``*_primary`` plus read/regional/reporting/failover
  replica tables holding ``record_json``. Every table is loaded separately so a
  copy surviving only on a replica (replication drift) stays visible.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import EvidenceFile, Observation, Scope
from .normalize import record_to_obs
from .records import COLLECTION_CATEGORY

INVENTORY_TABLE_SYSTEM = {
    "customer_profiles": "account_service",
    "customer_search_documents": "search_service",
    "customer_analytics_profiles": "analytics_platform",
    "support_records": "support_platform",
    "customer_exports": "export_service",
    "connector_subscriptions": "integration_service",
    "backup_restore_entries": "backup_service",
    "security_audit_records": "security_service",
}




def _rows(con: sqlite3.Connection, table: str):
    cur = con.execute(f'SELECT * FROM "{table}"')
    cols = [d[0] for d in cur.description]
    for row in cur:
        yield dict(zip(cols, row))


def load_sql(ef: EvidenceFile, path: Path) -> tuple[list[Observation], list[Scope]]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Captured at:\s*(\S+)", text)
    file_when = m.group(1) if m else ef.captured_at
    con = sqlite3.connect(":memory:")
    try:
        return _load(con, text, ef, file_when)
    finally:
        con.close()


def _load(con: sqlite3.Connection, text: str, ef: EvidenceFile,
          file_when: str) -> tuple[list[Observation], list[Scope]]:
    con.executescript(text)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    obs: list[Observation] = []
    scopes: list[Scope] = []

    if "snapshot_scope" in tables:                       # inventory layout
        scope_rows = {r["origin_system"]: r["captured_at"] for r in _rows(con, "snapshot_scope")}
        inv_scopes: list[Scope] = []
        for table, system in INVENTORY_TABLE_SYSTEM.items():
            if table not in tables:
                continue
            present: set[str] = set()
            for r in _rows(con, table):
                o = record_to_obs(r, evidence_id=ef.file_id,
                                  observed_at=scope_rows.get(system) or r.get("updated_at"),
                                  source=f"{ef.path}:{table}", system_hint=system,
                                  present_by_listing=True)
                if o:
                    o.fields["_location"] = table
                    obs.append(o)
                    present.add(o.resource_id)
            if system in scope_rows:
                inv_scopes.append(Scope(ef.file_id, system, scope_rows[system], table, present))
        covered = set().union(*(o.ident_values() for o in obs)) if obs else set()
        for sc in inv_scopes:
            sc.subjects = covered
        return obs, inv_scopes

    for table in tables:                                  # topology layout
        present_by_system: dict[str, set[str]] = {}
        for r in _rows(con, table):
            if "record_json" in r:
                rec = json.loads(r["record_json"])
                rec.setdefault("resource_id", r["resource_id"])
                hint_sys = r.get("origin_system")
                cat = COLLECTION_CATEGORY.get(r.get("collection_name") or "")
                # every table in one topology capture is read at the same moment, so a
                # copy surviving on a replica competes with the primary at capture time
                when = file_when
            else:                                         # flat profile/search tables
                rec = dict(r)
                hint_sys, cat, when = None, None, file_when
            o = record_to_obs(rec, evidence_id=ef.file_id, observed_at=when,
                              source=f"{ef.path}:{table}", system_hint=hint_sys,
                              category_hint=cat, present_by_listing=True)
            if o:
                o.fields["_location"] = table
                obs.append(o)
                present_by_system.setdefault(o.system_id or "", set()).add(o.resource_id)
        for system, present in present_by_system.items():
            if system:
                scopes.append(Scope(ef.file_id, system, file_when, table, present))
    return obs, scopes
