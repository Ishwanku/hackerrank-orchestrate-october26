"""Evidence graph: identifier <-> resource links, built once, queried per case.

Nodes are identifier values and resource ids; an edge exists when an
observation of a resource carries that identifier (in an identifier field or
mentioned in its free text). A subject's resources are all resources reachable
from any of its link keys through observations visible at ``audit_at``.

A second, smaller edge set records lineage between resources stated by the
evidence itself (a search document's ``source_resource_id``; a connector or
restore job that "repopulated downstream resource search_N").
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .identity import Subject
from .models import Observation
from .world import World


@dataclass
class Link:
    resource_id: str
    via: str              # identifier value that matched
    evidence_id: str
    observed_at: str


class EvidenceGraph:
    def __init__(self, world: World):
        self.world = world
        self.ident_to_obs: dict[str, list[Observation]] = defaultdict(list)
        self.lineage: dict[str, set[str]] = defaultdict(set)   # resource -> related resources
        for o in world.observations + world.claims:
            for v in o.ident_values():
                self.ident_to_obs[v].append(o)
            src = o.fields.get("source_resource_id")
            if isinstance(src, str) and src:
                self.lineage[src].add(o.resource_id)
                self.lineage[o.resource_id].add(src)
            for rel in o.fields.get("related", []) or []:
                self.lineage[o.resource_id].add(rel)

    def visible(self, o: Observation, audit_at: str) -> bool:
        """Evidence is usable for a case only if it existed at audit_at."""
        if o.kind == "claim":
            return o.observed_at <= audit_at
        cap = self.world.evidence_time(o.evidence_id)
        return cap is not None and cap <= audit_at and (not o.observed_at or o.observed_at <= audit_at)

    def links(self, subject: Subject, audit_at: str) -> dict[str, list[Link]]:
        out: dict[str, list[Link]] = defaultdict(list)
        for key in sorted(subject.link_keys):
            for o in self.ident_to_obs.get(key, []):
                if self.visible(o, audit_at):
                    out[o.resource_id].append(Link(o.resource_id, key, o.evidence_id, o.observed_at))
        return dict(out)
