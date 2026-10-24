"""Policy + deterministic planner: resource states -> ordered steps.

Each relevant resource gets a required end state from deletion_rules.csv. The
gap between its state at audit_at and that requirement yields at most one
finding, one remediation and one verification. Ordering is purely a sort key
(phase, operation table order, system_id, resource_id), so it cannot drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import OP_RANK, OP_STATE, PHASE_RANK, OP_PHASE, default_category
from .models import Step
from .state import ResourceState
from .world import World

# data category -> required end state (deletion_rules.csv)
REQUIRED = {
    "USER_PROFILE": "ABSENT", "SECONDARY_IDENTIFIER": "ABSENT",
    "SEARCH_INDEX_ENTRY": "ABSENT", "CACHE_ENTRY": "ABSENT",
    "SUPPORT_ATTACHMENT": "ABSENT", "USER_EXPORT": "ABSENT",
    "MARKETING_PROFILE": "ABSENT",
    "SUPPORT_MESSAGE": "REDACTED", "EMAIL_DELIVERY_LOG": "REDACTED",
    "ACCOUNT_TOMBSTONE": "REDACTED",
    "ANALYTICS_PROFILE": "ANONYMIZED", "PRODUCT_TELEMETRY": "ANONYMIZED",
    "SECURITY_AUDIT_LOG": "PRESENT", "LEGAL_HOLD_RECORD": "PRESENT",
    "BACKUP_ARCHIVE": "BLOCKED", "DATA_FLOW": "DISABLED",
}

ATTACHMENT_HINTS = ("file_name", "storage_class", "uploaded_by")


def category_of(world: World, rid: str) -> str:
    cat = default_category(rid) or "UNKNOWN"
    # a contact-list entry keyed only by the email hash (opt-in flag, contact
    # lookup) is a secondary identifier, whatever system holds it -> DELETE
    for o in world.by_resource.get(rid, []):
        if "email_opt_in" in o.fields or "contact_lookup" in str(o.fields.get("_event") or ""):
            return "SECONDARY_IDENTIFIER"
    if cat == "SUPPORT_MESSAGE":
        for o in world.by_resource.get(rid, []):
            if o.category == "SUPPORT_ATTACHMENT" or any(k in o.fields for k in ATTACHMENT_HINTS) \
                    or "attachment" in str(o.fields.get("_event") or ""):
                return "SUPPORT_ATTACHMENT"
        # the workflow's own choice of action reveals how it classified the record:
        # a support item it tried to DELETE (not REDACT) belongs only to the subject
        acts = {o.fields.get("event_type") for o in world.by_resource.get(rid, [])
                if o.kind == "claim" and o.fields.get("source_system") == "deletion_worker"}
        if "DELETE_RECORD" in acts and "REDACT_RECORD" not in acts:
            return "SUPPORT_ATTACHMENT"
    return cat


@dataclass
class Gap:
    finding: Optional[str]
    remediation: Optional[str]
    verification: Optional[str]


def gap_for(st: ResourceState) -> Gap:
    req = REQUIRED.get(st.category)
    if req is None:
        return Gap(None, None, None)
    if req == "ABSENT":
        if st.exists:
            return Gap("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")
        return Gap(None, None, "VERIFY_RECORD_ABSENT")
    if req == "REDACTED":
        if st.exists and st.exposes_direct:
            return Gap("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")
        if st.exists is False:
            return Gap(None, None, "VERIFY_RECORD_ABSENT")
        return Gap(None, None, "VERIFY_RECORD_REDACTED")
    if req == "ANONYMIZED":
        if st.exists and (st.exposes_direct or st.exposes_reference):
            return Gap("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED")
        if st.exists is False:
            return Gap(None, None, "VERIFY_RECORD_ABSENT")
        return Gap(None, None, "VERIFY_RECORD_ANONYMIZED")
    if req == "PRESENT":
        return Gap(None, None, "VERIFY_RECORD_PRESENT")
    if req == "DISABLED":
        if st.flow_enabled:
            return Gap("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED")
        return Gap(None, None, "VERIFY_DATA_FLOW_DISABLED")
    if req == "BLOCKED":
        if st.restore_allowed:
            return Gap("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED")
        return Gap(None, None, "VERIFY_RESTORE_BLOCKED")
    return Gap(None, None, None)


def sort_key(s: Step):
    return (PHASE_RANK[s.phase], OP_RANK[s.operation], s.system_id, s.resource_id)


def plan(states: list[ResourceState]) -> tuple[str, list[Step]]:
    steps: list[Step] = []
    gaps = [(st, gap_for(st)) for st in states]
    incomplete = any(g.finding for _, g in gaps)
    if not incomplete:
        # a COMPLETE verdict must cite evidence for every check; a resource with no
        # visible observation cannot be proven either way, so it is left out
        gaps = [(st, g) for st, g in gaps if st.exists is not None]
    for st, g in gaps:
        if g.finding:
            steps.append(Step("FINDING", st.system_id, st.resource_id, g.finding,
                              OP_STATE[g.finding], st.evidence_id))
            steps.append(Step("REMEDIATION", st.system_id, st.resource_id, g.remediation,
                              OP_STATE[g.remediation], ""))
        if g.verification:
            steps.append(Step("VERIFICATION", st.system_id, st.resource_id, g.verification,
                              OP_STATE[g.verification], "" if incomplete else st.evidence_id))
    steps.sort(key=sort_key)
    assert all(OP_PHASE[s.operation] == s.phase for s in steps)
    return ("INCOMPLETE" if incomplete else "COMPLETE"), steps
