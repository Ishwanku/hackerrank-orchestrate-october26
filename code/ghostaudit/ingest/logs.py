"""Loader for evidence/logs/*.log.

Six line dialects appear (key=value, JSON-per-line, syslog RFC5424, bracketed,
pipe-separated, and cloud-runtime lines with an escaped key=value ``message``).
Each line is parsed into (timestamp, service, trace_id, fields). A lookup is
usually split over several lines sharing a trace_id: the *started* line carries
the lookup key (an email / user id), the *completed* line carries the
resource_id and the outcome. Lines are therefore merged per trace before
being turned into observations, so the resource is linked to the identifier
that was queried even when the read-back returned 404.

Lines without a resource_id (connection pools, retries, heartbeats, DNS cache)
are noise and produce nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from ..models import EvidenceFile, Observation
from .normalize import record_to_obs

KV_RE = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(.*)$")
SYSLOG_RE = re.compile(r"^<\d+>\d+\s+(\S+)\s+(\S+)\s+(\S+)\s+-\s+-\s+(.*)$")
BRACKET_RE = re.compile(r"^\[(\w+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s+(\w+):\s*(.*)$")
PIPE_RE = re.compile(r"^\|?\s*(\w+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\w+)\s*\|\s*(.*)$")

COMPLETED_RE = re.compile(r"(_completed|_read|_scan|_heartbeat|_evaluated|_loaded)$")

# Normalise service names used in some exports to the owning system.
SERVICE_ALIAS = {"profile_service": "account_service"}


def _kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in KV_RE.findall(text):
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1].replace('\\"', '"')
        out[k] = v
    return out


def parse_line(line: str) -> Optional[tuple[str, dict[str, Any]]]:
    m = TS_RE.match(line.strip())
    if not m:
        return None
    ts, rest = m.groups()
    d: dict[str, Any]
    if rest.startswith("{"):
        try:
            d = json.loads(rest)
        except json.JSONDecodeError:
            return None
    elif (s := SYSLOG_RE.match(rest)):
        _, service, trace, body = s.groups()
        d = _kv(body)
        d.setdefault("service", service)
        d.setdefault("trace_id", trace)
    elif (b := BRACKET_RE.match(rest)):
        _, service, trace, event, body = b.groups()
        d = _kv(body)
        d.update(service=service, trace_id=trace, event=event)
    elif (p := PIPE_RE.match(rest)):
        _, service, trace, event, body = p.groups()
        d = _kv(body)
        d.update(service=service, trace_id=trace, event=event)
    else:
        d = _kv(rest)
        if "message" in d and "function" in d:            # cloud runtime export
            inner = _kv(d.pop("message"))
            d.update(inner)
            d.setdefault("service", d.get("function"))
            d.setdefault("trace_id", d.get("requestId"))
    if not d:
        return None
    svc = d.get("service")
    if isinstance(svc, str):
        d["service"] = SERVICE_ALIAS.get(svc, svc)
    return ts, d


def load_log(ef: EvidenceFile, path: Path) -> list[Observation]:
    parsed: list[tuple[int, str, dict[str, Any]]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        r = parse_line(line)
        if r:
            parsed.append((n, r[0], r[1]))

    # merge context per trace (lookup keys from *_started lines)
    context: dict[str, dict[str, Any]] = {}
    for _, _, d in parsed:
        trace = d.get("trace_id")
        if not trace:
            continue
        ctx = context.setdefault(trace, {})
        for k in ("lookup_key", "match_key", "scan_key", "subject_ref", "subject_key",
                  "owner_key", "correlation_key"):
            if d.get(k):
                ctx.setdefault(k, d[k])

    out: list[Observation] = []
    for n, ts, d in parsed:
        if not d.get("resource_id"):
            continue
        rec = dict(d)
        for k, v in context.get(d.get("trace_id") or "", {}).items():
            rec.setdefault(k, v)
        # drop transport noise that would confuse field-based state inference
        for k in ("level", "severity", "logger", "instance", "pod", "region", "attempt",
                  "requestId", "function"):
            rec.pop(k, None)
        o = record_to_obs(rec, evidence_id=ef.file_id, observed_at=ts,
                          source=f"{ef.path}:{n}", system_hint=d.get("system") or d.get("service"))
        if o:
            event = str(d.get("event") or "")
            o.fields["_event"] = event
            # a completed read / scan / heartbeat that returns the record (and
            # reported no miss) shows the record existed at that moment
            if o.exists is None and COMPLETED_RE.search(event):
                o.exists = True
            out.append(o)
    return out
