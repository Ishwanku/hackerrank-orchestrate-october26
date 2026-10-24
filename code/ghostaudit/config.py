"""Static vocabulary: systems, categories and the official step contract.

Everything here is taken from problem_statement.md / AGENTS.md or derived from
participant data (resource-id prefixes and the systems that own them).
"""
from __future__ import annotations

# Resource-id prefix -> owning system_id (as used in sample_output.csv) and
# deletion_rules.csv data category. Prefixes are matched longest-first.
PREFIX_TABLE: dict[str, tuple[str, str]] = {
    "email_delivery": ("email_delivery_service", "EMAIL_DELIVERY_LOG"),
    "audit_record": ("security_service", "SECURITY_AUDIT_LOG"),
    "legal_hold": ("legal_service", "LEGAL_HOLD_RECORD"),
    "data_flow": ("integration_service", "DATA_FLOW"),
    "tombstone": ("identity_service", "ACCOUNT_TOMBSTONE"),
    "analytics": ("analytics_platform", "ANALYTICS_PROFILE"),
    "telemetry": ("analytics_platform", "PRODUCT_TELEMETRY"),
    "marketing": ("marketing_platform", "MARKETING_PROFILE"),
    "account": ("account_service", "USER_PROFILE"),
    "search": ("search_service", "SEARCH_INDEX_ENTRY"),
    "support": ("support_platform", "SUPPORT_MESSAGE"),   # refined per record
    "export": ("export_service", "USER_EXPORT"),
    "backup": ("backup_service", "BACKUP_ARCHIVE"),
    "object": ("object_storage", "USER_EXPORT"),           # refined per record
    "cache": ("cache_service", "CACHE_ENTRY"),
}
_PREFIXES = sorted(PREFIX_TABLE, key=len, reverse=True)


def prefix_of(resource_id: str) -> str | None:
    for p in _PREFIXES:
        if resource_id.startswith(p + "_"):
            return p
    return None


def system_of(resource_id: str) -> str | None:
    p = prefix_of(resource_id)
    return PREFIX_TABLE[p][0] if p else None


def default_category(resource_id: str) -> str | None:
    p = prefix_of(resource_id)
    return PREFIX_TABLE[p][1] if p else None


# ---- Official output contract (problem_statement.md, "Allowed Operations") ----
PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")

OPERATIONS: list[tuple[str, str, str]] = [  # (phase, operation, state), in table order
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
]
OP_RANK = {op: i for i, (_, op, _) in enumerate(OPERATIONS)}
OP_STATE = {op: state for _, op, state in OPERATIONS}
OP_PHASE = {op: phase for phase, op, _ in OPERATIONS}
PHASE_RANK = {p: i for i, p in enumerate(PHASES)}

STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
OUTPUT_HEADER = ["case_id", "deletion_status", "steps_json"]
