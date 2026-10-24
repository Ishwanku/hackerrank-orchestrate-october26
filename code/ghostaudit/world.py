"""Load every participant-facing input once into an immutable-ish ``World``."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .ingest.logs import load_log
from .ingest.records import load_json, load_text
from .ingest.sqlsnap import load_sql
from .models import Scope
from .ingest.tables import load_activity, load_manifest, load_requests, read_csv
from .models import EvidenceFile, Observation, Request


@dataclass
class World:
    dataset: Path
    requests: list[Request]
    sample_requests: list[Request]
    identities: list[dict[str, str]]
    audit_log: list[dict[str, str]]
    rules: list[dict[str, str]]
    manifest: dict[str, EvidenceFile]
    observations: list[Observation]          # evidence-file observations
    claims: list[Observation]                # system_activity rows
    scopes: list[Scope]
    coverage: dict[str, int] = field(default_factory=dict)   # file_id -> #observations
    by_resource: dict[str, list[Observation]] = field(default_factory=dict)

    def evidence_time(self, evidence_id: str) -> Optional[str]:
        """Capture time used for the 'never cite later evidence' rule."""
        ef = self.manifest.get(evidence_id)
        if ef:
            return ef.captured_at
        return None


def load_world(dataset: Path, extra_observations: Optional[list[Observation]] = None) -> World:
    manifest = {ef.file_id: ef for ef in load_manifest(dataset / "evidence_files.csv")}
    observations: list[Observation] = []
    scopes: list[Scope] = []
    coverage: dict[str, int] = {}
    for ef in sorted(manifest.values(), key=lambda e: e.file_id):
        path = dataset / ef.path
        suffix = path.suffix.lower()
        got: list[Observation] = []
        if suffix == ".json":
            got, sc = load_json(ef, path)
            scopes += sc
        elif suffix == ".txt":
            got = load_text(ef, path)
        elif suffix == ".sql":
            got, sc = load_sql(ef, path)
            scopes += sc
        elif suffix == ".log":
            got = load_log(ef, path)
        # .pdf / .png are handled by the perception layer (extra_observations)
        coverage[ef.file_id] = len(got)
        observations += got
    if extra_observations:
        for o in extra_observations:
            coverage[o.evidence_id] = coverage.get(o.evidence_id, 0) + 1
        observations += extra_observations

    by_resource: dict[str, list[Observation]] = defaultdict(list)
    for o in observations:
        by_resource[o.resource_id].append(o)
    claims = load_activity(dataset / "system_activity.csv")
    for c in claims:
        by_resource[c.resource_id].append(c)
    for lst in by_resource.values():
        lst.sort(key=lambda o: (o.observed_at, o.evidence_id))

    return World(
        dataset=dataset,
        requests=load_requests(dataset / "deletion_requests.csv"),
        sample_requests=load_requests(dataset / "sample_deletion_requests.csv"),
        identities=read_csv(dataset / "user_identities.csv"),
        audit_log=read_csv(dataset / "user_audit_log.csv"),
        rules=read_csv(dataset / "deletion_rules.csv"),
        manifest=manifest,
        observations=observations,
        claims=claims,
        scopes=scopes,
        coverage=coverage,
        by_resource=dict(by_resource),
    )
