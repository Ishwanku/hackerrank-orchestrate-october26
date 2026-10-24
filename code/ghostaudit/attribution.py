"""Which resources belong to which request.

Two sources, in order of trust:

1. **Evidence links** (graph.py): a resource whose evidence carries one of the
   subject's identifiers. Identity facts don't change over time, so links are
   taken from all evidence; *state* is still judged only at audit_at.

2. **Workflow attribution**: many records keep no identifier once treated (a
   404 profile, an anonymized analytics row). The only participant-visible tie
   is the deletion worker's own activity for the request. Measured on the 254
   evidence-linked accounts, the worker's primary-profile delete happens on the
   request's *reported day* and its reported result matches the request's
   reported_status (COMPLETE->SUCCESS, PARTIALLY_COMPLETE->PARTIAL,
   NOT_STARTED->FAILED) in 251/254 cases. Unowned worker actions are assigned
   to requests that still lack that resource type, using that key.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .config import prefix_of
from .graph import EvidenceGraph
from .identity import IdentityIndex
from .models import Request
from .world import World

STATUS_TO_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL",
                    "NOT_STARTED": "FAILED"}
# resource types the worker touches that commonly lose every identifier
WORKFLOW_TYPES = ("account", "analytics")


@dataclass
class Attribution:
    resources: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    via: dict[tuple[str, str], str] = field(default_factory=dict)   # (case, rid) -> how
    owner: dict[str, str] = field(default_factory=dict)             # rid -> user (evidence)


def _num(s: str) -> int:
    tail = s.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _stale_negative(world: World, rid: str, links, requested_at: str) -> bool:
    """A link seen only *before* the request, from evidence that never showed the
    record present (a 404 lookup, a catalog note), describes an earlier account
    lifecycle, not this request. Measured on samples: drops 3 wrong, 0 right."""
    if any(l.observed_at >= requested_at for l in links):
        return False
    ids = {l.evidence_id for l in links}
    return not any(o.exists for o in world.by_resource.get(rid, [])
                   if o.kind == "observed" and o.evidence_id in ids)


def attribute(world: World, idx: IdentityIndex, graph: EvidenceGraph,
              requests: list[Request]) -> Attribution:
    att = Attribution()
    user_of: dict[str, str] = {}
    for r in requests:
        uids = idx.resolve(r.email)
        if uids:
            user_of[r.case_id] = uids[0]

    # 1. evidence links (all users, so foreign records are known as foreign)
    links_of: dict[str, dict] = {}
    for uid in idx.current:
        links_of[uid] = graph.links(idx.subject(uid), "9999-12-31T23:59:59Z")
        for rid in links_of[uid]:
            att.owner.setdefault(rid, uid)
    for r in requests:
        uid = user_of.get(r.case_id)
        for rid, links in (links_of.get(uid) or {}).items():
            if _stale_negative(world, rid, links, r.requested_at):
                att.via[(r.case_id, rid)] = "dropped:pre-request-negative"
                continue
            att.resources[r.case_id].add(rid)
            att.via[(r.case_id, rid)] = "evidence"

    # 2. workflow attribution of unowned deletion-worker actions
    for rtype in WORKFLOW_TYPES:
        candidates: dict[tuple, list[str]] = defaultdict(list)
        for c in world.claims:
            if c.fields.get("source_system") != "deletion_worker" or c.resource_id in att.owner:
                continue
            if prefix_of(c.resource_id) != rtype:
                continue
            key_result = c.status if rtype == "account" else "*"
            candidates[(c.observed_at[:10], key_result)].append(c.resource_id)
        needy: dict[tuple, list[Request]] = defaultdict(list)
        for r in requests:
            if any(prefix_of(x) == rtype for x in att.resources[r.case_id]):
                continue
            key_result = STATUS_TO_RESULT.get(r.reported_status, "") if rtype == "account" else "*"
            needy[(r.reported_at[:10], key_result)].append(r)
        for key, rids in candidates.items():
            cases = sorted(needy.get(key, []), key=lambda r: _num(r.case_id))
            rids = sorted(set(rids), key=_num)
            if rtype == "analytics" and len(cases) != len(rids):
                # ponytail: analytics are attributed only when the day's counts
                # match exactly; otherwise the guess is worse than omission.
                continue
            # ponytail: ties inside one (day, result) group are broken by id order,
            # which measured at chance level; the README reports this as a known limit.
            for r, rid in zip(cases, rids):
                att.resources[r.case_id].add(rid)
                att.via[(r.case_id, rid)] = "workflow" if len(cases) == 1 else "workflow-tie"
    return att
