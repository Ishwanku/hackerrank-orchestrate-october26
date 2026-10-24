"""Reconstruct one resource's state at a case's audit_at.

Rule: the latest *observation* at or before audit_at decides; claims (workflow
results) never override an observation. Complete listings (Scope) contribute
an "absent" observation for every in-scope resource they do not list. When
several observations share the latest timestamp, any surviving copy wins
(a replica still holding the record means the data still exists).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .identity import Subject
from .models import Scope
from .models import DIRECT_ID_FIELDS, REFERENCE_FIELDS, Observation, norm_ident
from .world import World

REDACTED_MARKERS = ("[redacted]", "redacted")


@dataclass
class ResourceState:
    resource_id: str
    system_id: str
    category: str
    exists: Optional[bool]               # None = no visible observation
    evidence_id: str = ""                # observation proving the state
    observed_at: str = ""
    exposes_direct: bool = False         # name/email/phone/hash still present
    exposes_reference: bool = False      # user_id / subject reference present
    flow_enabled: Optional[bool] = None  # DATA_FLOW
    restore_allowed: Optional[bool] = None  # BACKUP_ARCHIVE
    history: list[str] = field(default_factory=list)  # audit trail lines


def _bool(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "enabled", "allowed"):
            return True
        if s in ("false", "0", "no", "disabled", "blocked"):
            return False
    return None


def _value_set(v) -> bool:
    return v is not None and not (isinstance(v, str) and (not v.strip() or v.strip().lower() in
                                                          ("null", "none", *REDACTED_MARKERS)))


def content_flags(o: Observation, subject: Subject) -> tuple[bool, bool]:
    """(exposes direct identifiers, exposes stable reference) for a present record."""
    f = o.fields
    status = (o.status or "").upper()
    if status in ("ANONYMIZED", "REDACTED"):
        return False, False
    if status == "IDENTIFIABLE":
        return True, True
    direct = any(_value_set(f.get(k)) for k in DIRECT_ID_FIELDS)
    if not direct:
        keys = subject.exposure_keys
        direct = any(m in keys for m in f.get("_mentions", []))
        di = f.get("direct_identifiers")
        if di is not None and str(di).isdigit() and int(str(di)) > 0:
            direct = True
        if _value_set(f.get("matched_value")) and f.get("detector") == "direct_identifier":
            direct = True
    ref = any(_value_set(f.get(k)) for k in REFERENCE_FIELDS)
    return direct, ref


def resource_state(world: World, rid: str, audit_at: str, subject: Subject,
                   scopes_by_system: dict[str, list[Scope]], system: str,
                   category: str) -> ResourceState:
    st = ResourceState(rid, system, category, None)
    obs: list[Observation] = []
    for o in world.by_resource.get(rid, []):
        if o.kind != "observed" or o.exists is None:
            continue
        cap = world.evidence_time(o.evidence_id)
        if cap is None or cap > audit_at or (o.observed_at and o.observed_at > audit_at):
            continue
        obs.append(o)
    # complete listings that do not contain this resource -> absent at capture time
    for sc in scopes_by_system.get(system, []):
        cap = world.evidence_time(sc.evidence_id)
        if sc.subjects is not None and not (sc.subjects & subject.link_keys):
            continue
        if cap and cap <= audit_at and sc.captured_at <= audit_at and rid not in sc.present:
            obs.append(Observation(evidence_id=sc.evidence_id, observed_at=sc.captured_at,
                                   resource_id=rid, system_id=system, exists=False,
                                   source=f"scope:{sc.location}"))
    if not obs:
        return st
    latest = max(o.observed_at for o in obs)
    at_latest = sorted((o for o in obs if o.observed_at == latest), key=lambda o: o.evidence_id)
    present = [o for o in at_latest if o.exists]
    chosen = present[0] if present else at_latest[0]
    st.exists = bool(present)
    st.evidence_id = chosen.evidence_id
    st.observed_at = latest
    st.history = [f"{o.observed_at} {o.evidence_id} exists={o.exists} {o.source}" for o in
                  sorted(obs, key=lambda o: (o.observed_at, o.evidence_id))]
    if present:
        d = r = False
        for o in present:
            od, orf = content_flags(o, subject)
            d, r = d or od, r or orf
            fe = _bool(o.fields.get("enabled"))
            if fe is None and (o.status or "") in ("ACTIVE", "DISABLED") and category == "DATA_FLOW":
                fe = o.status == "ACTIVE"
            if fe is not None:
                st.flow_enabled = fe if st.flow_enabled is None else (st.flow_enabled or fe)
            ra = _bool(o.fields.get("restore_allowed"))
            if ra is None and o.fields.get("eligible") is not None:
                ra = _bool(o.fields.get("eligible")) and not _bool(o.fields.get("deletion_block"))
            if ra is None and (o.status or "") in ("ACTIVE", "BLOCKED") and category == "BACKUP_ARCHIVE":
                ra = o.status == "ACTIVE"
            if ra is not None:
                st.restore_allowed = ra if st.restore_allowed is None else (st.restore_allowed or ra)
        st.exposes_direct, st.exposes_reference = d, r
    return st


def scopes_index(world: World) -> dict[str, list[Scope]]:
    out: dict[str, list[Scope]] = {}
    for sc in world.scopes:
        out.setdefault(sc.system, []).append(sc)
    return out


__all__ = ["ResourceState", "resource_state", "scopes_index", "norm_ident"]
