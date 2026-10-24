"""Loaders for the top-level CSV inputs and system_activity claims."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from ..config import system_of
from ..models import EvidenceFile, Observation, Request
from .normalize import EMAIL_RE, USER_RE

RID_RE = re.compile(r"\b(?:account|search|support|analytics|export|cache|email_delivery|data_flow|"
                    r"backup|tombstone|audit_record|legal_hold|marketing|object|telemetry)_\d+\b")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_requests(path: Path) -> list[Request]:
    return [Request(**{k: r[k] for k in Request.__dataclass_fields__}) for r in read_csv(path)]


def load_manifest(path: Path) -> list[EvidenceFile]:
    return [EvidenceFile(r["file_id"], r["file_path"], r["origin"], r["captured_at"])
            for r in read_csv(path)]


def load_activity(path: Path) -> list[Observation]:
    """Every activity row becomes a *claim*. Claims never prove resource state by
    themselves, but they carry two kinds of useful structure:
      * ``related``: another resource named in the details (a connector or a
        restore job that repopulated a downstream search entry);
      * identifiers linked by the data catalog (LINK_RESOURCE_IDENTITY rows).
    """
    out: list[Observation] = []
    for r in read_csv(path):
        rid = r["resource_id"]
        details = r["details"]
        related = sorted(set(RID_RE.findall(details)) - {rid})
        fields = {
            "event_type": r["event_type"],
            "reported_result": r["reported_result"],
            "source_system": r["source_system"],
            "target_system": r["target_system"],
            "details": details,
            "related": related,
        }
        if r["event_type"] == "LINK_RESOURCE_IDENTITY":
            fields["_mentions"] = sorted({x.lower() for x in EMAIL_RE.findall(details)} |
                                         set(USER_RE.findall(details)))
        out.append(Observation(evidence_id=r["activity_id"], observed_at=r["event_time"],
                               resource_id=rid, system_id=system_of(rid) or r["target_system"],
                               kind="claim", category=None, exists=None,
                               status=r["reported_result"], fields=fields,
                               source=f"system_activity.csv:{r['activity_id']}"))
    out.sort(key=lambda o: (o.observed_at, o.evidence_id))
    return out
