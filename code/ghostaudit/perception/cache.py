"""Load cached facts extracted from PDFs and screenshots.

Extraction (perception/extract.py) runs once, writes JSON to code/cache/, and
every later run only reads that cache -- so the pipeline stays deterministic
and offline. Missing cache simply means no multimodal observations.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..ingest.normalize import record_to_obs
from ..ingest.tables import load_manifest
from ..models import Observation


def load_perception(dataset: Path, cache_dir: Path) -> list[Observation]:
    if not cache_dir.exists():
        return []
    manifest = {ef.file_id: ef for ef in load_manifest(dataset / "evidence_files.csv")}
    out: list[Observation] = []
    for path in sorted(cache_dir.glob("evidence_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        ef = manifest.get(data.get("file_id", ""))
        if not ef:
            continue
        for i, rec in enumerate(data.get("records", [])):
            o = record_to_obs(rec, evidence_id=ef.file_id,
                              observed_at=rec.get("observed_at") or ef.captured_at,
                              source=f"{ef.path}:perception[{i}]",
                              present_by_listing=rec.get("exists") is None)
            if o:
                if isinstance(rec.get("exists"), bool):
                    o.exists = rec["exists"]
                out.append(o)
    return out
