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
   NOT_STARTED->FAILED) in 251/254 cases. An unowned primary-profile deletion
   is attributed only when that key matches exactly one candidate and one
   request. This is an *inferred* link (timestamp + the workflow's own status,
   AGENTS.md 6.6 "timestamps ... and other grounded links"), never presented as
   confirmed identity; the audit trail labels it ``inferred:workflow-unique``.

   Anonymized analytics rows with no identifier are NOT attributed: nothing in
   the specification or the evidence ties them to a person, and count matching
   would be guesswork.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .config import prefix_of
from .graph import EvidenceGraph
from .identity import IdentityIndex
from .intent import classify
from .models import Request
from .world import World

STATUS_TO_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL",
                    "NOT_STARTED": "FAILED"}


@dataclass
class Attribution:
    resources: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    via: dict[tuple[str, str], str] = field(default_factory=dict)   # (case, rid) -> how
    owner: dict[str, str] = field(default_factory=dict)             # rid -> user (evidence)
    # (case, resource type, candidate ids) left open because the match was not unique
    unresolved: list[tuple[str, str, list[str]]] = field(default_factory=list)



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

    # 2. workflow attribution of unowned primary-profile deletions.
    # Only a *unique* match is accepted: exactly one unowned account deletion
    # and exactly one deletion request still lacking an account share the key
    # (reported day, reported result). Anything else (a tie, a count mismatch)
    # is left unattributed -- an unsupported identity claim is worse than a gap.
    candidates: dict[tuple, set[str]] = defaultdict(set)
    for c in world.claims:
        if (c.fields.get("source_system") == "deletion_worker"
                and c.fields.get("event_type") == "DELETE_RECORD"
                and prefix_of(c.resource_id) == "account" and c.resource_id not in att.owner):
            candidates[(c.observed_at[:10], c.status)].add(c.resource_id)
    needy: dict[tuple, list[Request]] = defaultdict(list)
    for r in requests:
        if not classify(r.request_text)[0]:
            continue
        if any(prefix_of(x) == "account" for x in att.resources[r.case_id]):
            continue
        needy[(r.reported_at[:10], STATUS_TO_RESULT.get(r.reported_status, ""))].append(r)
    for key, rids in candidates.items():
        cases = needy.get(key, [])
        if len(cases) == 1 and len(rids) == 1:
            rid = next(iter(rids))
            att.resources[cases[0].case_id].add(rid)
            att.via[(cases[0].case_id, rid)] = "inferred:workflow-unique"
        else:
            for r in cases:
                att.unresolved.append((r.case_id, "account", sorted(rids)))
    return att
