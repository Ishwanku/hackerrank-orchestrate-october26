"""End-to-end decision for a list of requests."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .attribution import Attribution, attribute
from .config import system_of
from .graph import EvidenceGraph
from .identity import IdentityIndex
from .intent import classify
from .models import Request, Step
from .planner import category_of, plan
from .state import ResourceState, resource_state, scopes_index
from .world import World


@dataclass
class CaseResult:
    case_id: str
    status: str
    steps: list[Step]
    trail: dict = field(default_factory=dict)   # audit trail, not part of output.csv

    def steps_json(self) -> str:
        return json.dumps([s.as_dict(i) for i, s in enumerate(self.steps, 1)],
                          ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Auditor:
    def __init__(self, world: World):
        self.world = world
        self.idx = IdentityIndex(world.identities, world.audit_log)
        self.graph = EvidenceGraph(world)
        self.scopes = scopes_index(world)
        # attribution competes across *every* request in the activity stream
        self.att: Attribution = attribute(world, self.idx, self.graph,
                                          world.requests + world.sample_requests)

    def audit(self, r: Request) -> CaseResult:
        ok, why = classify(r.request_text)
        if not ok:
            return CaseResult(r.case_id, "NOT_APPLICABLE", [], {"intent": why})
        uids = self.idx.resolve(r.email)
        if not uids:
            # ponytail: unknown subject -> nothing can be verified; treated as incomplete-free
            return CaseResult(r.case_id, "COMPLETE", [], {"intent": why, "identity": "unresolved"})
        subject = self.idx.subject(uids[0], r.audit_at)
        states: list[ResourceState] = []
        for rid in sorted(self.att.resources.get(r.case_id, ())):
            system = system_of(rid)
            if system is None:
                continue
            st = resource_state(self.world, rid, r.audit_at, subject, self.scopes, system,
                                category_of(self.world, rid))
            states.append(st)
        status, steps = plan(states)
        trail = {"intent": why, "user_id": subject.user_id,
                 "resources": {st.resource_id: {"via": self.att.via.get((r.case_id, st.resource_id)),
                                                "category": st.category, "exists": st.exists,
                                                "evidence": st.evidence_id,
                                                "direct": st.exposes_direct,
                                                "ref": st.exposes_reference,
                                                "flow": st.flow_enabled,
                                                "restore": st.restore_allowed,
                                                "history": st.history[-4:]}
                               for st in states}}
        return CaseResult(r.case_id, status, steps, trail)
