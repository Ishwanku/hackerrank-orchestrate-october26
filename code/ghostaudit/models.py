"""Core data types shared by every stage of the pipeline.

An ``Observation`` is one dated statement about one resource, taken from one
piece of participant-visible evidence. Everything downstream (identity linking,
state reconstruction, policy, planning) works on observations only, so each
loader's job is simply: turn a file into observations without losing facts.

``kind`` separates two levels of trust:
  * "observed" -- a read-back, snapshot, export or screenshot showing what the
    resource actually looked like at ``observed_at``.
  * "claim"    -- a workflow/activity row reporting that an operation was
    attempted and what result it *reported*. Claims never prove state on their
    own (problem statement, Rules section).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


def norm_ident(value: str) -> str:
    """Canonical form for identifier comparison: emails lower-cased, phone
    numbers reduced to digits ("tel:" prefix), everything else lower-cased."""
    v = value.strip()
    if "@" in v:
        return v.lower()
    digits = re.sub(r"\D", "", v)
    if v.startswith("+") and len(digits) >= 7:
        return "tel:" + digits
    return v.lower()

# Identifier-bearing field names found across the evidence formats. Values in
# these fields are compared (lower-cased) against a subject's identifier set.
IDENTIFIER_FIELDS = frozenset({
    "email", "phone", "email_hash", "name", "full_name", "display_name",
    "customer_email", "customer_reference", "subject_reference", "subject_selector",
    "user_id", "requester_email", "requester_name", "requester_phone",
    "owner_email", "owner_phone", "uploaded_by", "lookup_key", "match_key",
    "scan_key", "subject_ref", "subject_key", "correlation_key", "owner_key",
    "matched_value", "lookup_value", "query", "account",
})

# Direct identifiers that policy requires removed from redacted/anonymized
# records and tombstones (problem statement: name, email, phone, email hash).
DIRECT_ID_FIELDS = frozenset({
    "email", "phone", "email_hash", "name", "full_name", "display_name",
    "customer_email", "requester_email", "requester_name", "requester_phone",
    "owner_email", "owner_phone", "uploaded_by",
})

# A stable internal reference: allowed on tombstones and retained records,
# but still links analytics/telemetry records to the person (not anonymized).
REFERENCE_FIELDS = frozenset({"customer_reference", "subject_reference", "user_id",
                              "subject_selector"})


@dataclass
class Observation:
    evidence_id: str                 # file_id, activity_id or audit_id
    observed_at: str                 # ISO-8601 UTC, "Z" suffix
    resource_id: str
    system_id: Optional[str] = None  # service that owns the resource, if known
    kind: str = "observed"           # "observed" | "claim"
    category: Optional[str] = None   # e.g. USER_PROFILE, when evidence states it
    exists: Optional[bool] = None    # True present, False absent, None unknown
    status: Optional[str] = None     # FOUND / NOT_FOUND / IDENTIFIABLE / ANONYMIZED /
                                     # REDACTED / ACTIVE / DISABLED / BLOCKED / ...
    fields: dict[str, Any] = field(default_factory=dict)  # raw attributes
    source: str = ""                 # loader + location, for the audit trail

    def ident_values(self) -> set[str]:
        """All identifier-like values in this observation, lower-cased."""
        out: set[str] = set()
        for key, value in self.fields.items():
            if key in IDENTIFIER_FIELDS and isinstance(value, str) and value:
                v = value.strip()
                if v and v.lower() not in {"null", "none", "[redacted]", "redacted"}:
                    out.add(norm_ident(v))
        # identifiers mentioned inside free text (support messages, PDFs, OCR)
        for v in self.fields.get("_mentions", ()):
            out.add(norm_ident(v))
        return out


@dataclass
class EvidenceFile:
    file_id: str
    path: str          # relative to dataset/
    origin: str
    captured_at: str


@dataclass
class Request:
    case_id: str
    email: str
    requested_at: str
    reported_status: str
    reported_at: str
    audit_at: str
    request_text: str


@dataclass
class Step:
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str = ""

    def as_dict(self, step_no: int) -> dict[str, Any]:
        return {
            "step_no": step_no,
            "phase": self.phase,
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": self.state,
            "evidence_id": self.evidence_id,
        }


@dataclass
class Scope:
    """A capture that lists every record of ``system`` at ``captured_at``.

    ``subjects`` limits whose records the listing covers: ``None`` means the
    whole table was dumped (topology captures); otherwise only subjects whose
    identifiers appear in the same capture are covered (records-assurance
    bundles and inventories are targeted at a handful of people, so an empty
    collection there proves absence only for those people).
    """
    evidence_id: str
    system: str
    captured_at: str
    location: str
    present: set[str] = field(default_factory=set)
    subjects: Optional[set[str]] = None
