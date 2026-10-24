"""Turn any evidence record (dict) into an Observation.

The evidence formats disagree on field names (status_code vs http_status,
customer_reference vs subject_ref, owner_email vs uploaded_by, ...). This module
is the single place that understands those spellings, so the rest of the
pipeline sees one vocabulary.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..config import default_category, system_of
from ..models import IDENTIFIER_FIELDS, Observation, norm_ident

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+\d[\d \-()]{6,}\d")
USER_RE = re.compile(r"\buser_\d+\b")
NULLS = {"", "null", "none", "nil", "n/a"}

# explicit textual results seen across evidence
PRESENT_STATUSES = {"FOUND", "IDENTIFIABLE", "ANONYMIZED", "REDACTED", "ACTIVE",
                    "DISABLED", "BLOCKED", "PRESENT", "RETAINED", "ENABLED"}
ABSENT_STATUSES = {"NOT_FOUND", "ABSENT", "DELETED_RECORD", "MISSING"}


def clean(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in NULLS:
        return None
    return value


def flatten(rec: dict[str, Any], out: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Merge nested dicts (document, profile, hits.documents[0]) into one level.

    Outer keys win over inner keys so a wrapper's resource_id is kept.
    """
    out = {} if out is None else out
    nested: list[dict] = []
    for k, v in rec.items():
        if isinstance(v, dict):
            nested.append(v)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v) and k == "documents":
            nested.extend(v)
        else:
            out.setdefault(k.lower(), clean(v))
    for n in nested:
        if "documents" in n:  # search hits wrapper
            out.setdefault("total_hits", n.get("total"))
        flatten(n, out)
    return out


def mentions(fields: dict[str, Any]) -> list[str]:
    """Identifiers embedded in free-text fields (message text, excerpts, notes)."""
    found: list[str] = []
    for k, v in fields.items():
        if k in IDENTIFIER_FIELDS or not isinstance(v, str):
            continue
        found += EMAIL_RE.findall(v)
        found += [m for m in PHONE_RE.findall(v)]
        found += USER_RE.findall(v)
    return sorted({norm_ident(x) for x in found})


def infer_exists(fields: dict[str, Any], status: Optional[str]) -> Optional[bool]:
    if status in ABSENT_STATUSES:
        return False
    if status in PRESENT_STATUSES:
        return True
    for key in ("status_code", "http_status"):
        code = fields.get(key)
        if code is not None:
            code = str(code)
            if code == "404" or code == "410":
                return False
            if code.startswith("2"):
                return True
    rows = fields.get("rows")
    if rows is not None and str(rows).isdigit():
        return int(str(rows)) > 0
    hits = fields.get("total_hits")
    if hits is not None and str(hits).isdigit():
        return int(str(hits)) > 0
    res = fields.get("result")
    if isinstance(res, str):
        r = res.lower()
        if r in {"hit", "found"}:
            return True
        if r in {"miss", "not_found", "no_hit"}:
            return None if fields.get("cache") else False
    for flag in ("archive_present", "available"):
        if fields.get(flag) is not None:
            return str(fields[flag]).lower() == "true"
    return None


def record_to_obs(rec: dict[str, Any], *, evidence_id: str, observed_at: Optional[str],
                  source: str, system_hint: Optional[str] = None,
                  category_hint: Optional[str] = None, present_by_listing: bool = False,
                  kind: str = "observed") -> Optional[Observation]:
    fields = flatten(rec)
    rid = fields.get("resource_id")
    if not isinstance(rid, str) or not rid:
        return None
    rid = rid.strip()
    status = fields.get("result") if isinstance(fields.get("result"), str) and \
        fields["result"].isupper() else None
    category = fields.get("record_type") or category_hint
    system = fields.get("system") if isinstance(fields.get("system"), str) else None
    system = system_of(rid) or system or system_hint
    when = (fields.get("observed_at") or fields.get("recorded_at") or observed_at
            or fields.get("updated_at") or fields.get("captured_at"))
    exists = infer_exists(fields, status)
    if exists is None and present_by_listing:
        exists = True
    m = mentions(fields)
    if m:
        fields["_mentions"] = m
    return Observation(evidence_id=evidence_id, observed_at=str(when or ""), resource_id=rid,
                       system_id=system, kind=kind,
                       category=category or default_category(rid), exists=exists,
                       status=status, fields=fields, source=source)
