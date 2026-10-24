# Ghost Data Audit Agent

HackerRank Orchestrate, October 2026 — *Ghost Data Still Exists*. The challenge statement is in [`problem_statement.md`](problem_statement.md); the organiser's original README is kept as [`CHALLENGE_README.md`](CHALLENGE_README.md).

For each deletion request, the agent decides `COMPLETE`, `INCOMPLETE` or `NOT_APPLICABLE` and emits the ordered findings, remediation and verification steps. It is a **deterministic evidence-graph engine**: all 518 cases run in about 0.4 s with no model calls, and every step cites participant-visible evidence captured at or before the case's `audit_at`.

## Quick start (clean environment)

Requirements: Python ≥ 3.10. The pipeline uses the **standard library only** — no `pip install` needed.

```bash
git clone <this repository>
cd <repository>
# place the challenge dataset at ./dataset (as in the starter repo)
python3 code/main.py                 # -> ./output.csv (518 rows) + contract validation
python3 code/main.py --sample        # -> code/run/sample_pred.csv for the 32 samples
python3 code/evaluation/score.py     # metrics against dataset/sample_output.csv
python3 -m unittest discover -s code/tests -v   # 16 independent regression tests
python3 code/evaluation/ablation.py  # one-component-off study (Markdown table)
```

Expected output of the first command: `wrote …/output.csv rows=518 {'INCOMPLETE': 352, 'COMPLETE': 156, 'NOT_APPLICABLE': 10}` followed by `validation: OK`. Re-running it produces a byte-identical file.

Optional: `python3 code/main.py --trail` writes `code/run/audit_trail.jsonl`. For every case it records the intent decision and, for each resource, how it was linked (`evidence` or `inferred:workflow-unique`), its category, its state at `audit_at`, the cited evidence, and the last observations.

### Rebuilding the perception cache (optional)

Facts from the 4 PDFs and 11 screenshots are cached in `code/cache/*.json` and read by every run. To rebuild them:

```bash
python3 code/ghostaudit/perception/extract.py --force                     # pdftotext + tesseract, no model
python3 code/ghostaudit/perception/extract.py --backend anthropic --force # optional vision model
```

The `anthropic` backend reads `ANTHROPIC_API_KEY` from the environment or from a git-ignored `.env` (see `.env.example`). It was **not** used for the submitted output.

## How it works

```
deletion_requests ──► intent check ──► NOT_APPLICABLE ([])
        │ deletion
        ▼
identities + audit log ──► identity closure (all emails, phones, SHA-256 hashes, user_id)
                                   │
evidence (SQL, JSON, logs, txt,    ▼
PDF/PNG cache) + activity ──► evidence graph: identifier ↔ resource
                                   │  + unique workflow attribution (inferred)
                                   ▼
                     state at audit_at (latest observation wins; claims never override)
                                   ▼
                     policy (deletion_rules.csv → required end state)
                                   ▼
                     deterministic planner (canonical sort) ──► validator ──► output.csv
```

| Module (`code/ghostaudit/`) | Responsibility |
| --- | --- |
| `ingest/` | One loader per format → uniform `Observation` records. Handles 6 log dialects joined by `trace_id`, SQLite snapshots with primary and replica tables, records-assurance bundles, service exports, and the handover sheet. Marks *claims* (activity rows) separately from *observations*. |
| `perception/` | Cached facts from PDFs and screenshots; OCR emails are snapped only to known identities (closed world). |
| `identity.py` | Request email (current or historical) → user → every identifier ever held; exact matching only (look-alike decoys exist). |
| `graph.py` | Identifier ↔ resource index over all evidence; visibility respects capture time. |
| `attribution.py` | Links resources to a request: evidence links, plus a *unique* deletion-workflow match for accounts that kept no identifier. Ties are left unresolved. |
| `state.py` | Resource state at `audit_at`. Complete listings prove absence; partial snapshots only for the people they cover; a copy surviving on any replica counts as present. |
| `planner.py` | Category → required end state → finding / remediation / verification; official ordering by sort key. |
| `intent.py` | Deletion versus explicit non-deletion purpose, multilingual, negation-aware. |
| `validate.py` | Output contract checks, run on every write. |

## Key design decisions

1. **No LLM in the decision path.** Exact ids, order and evidence citations are what the grader rewards. Code guarantees them and an LLM only approximates them. Measured cost: 0 tokens (`code/evaluation/usage_report.md`).
2. **Observations outrank claims.** A workflow saying "deleted" is a claim; a read-back, a snapshot or a replica row is proof. The latest observation at or before `audit_at` decides.
3. **No unsupported identity claims.** When several requests could own an unlabelled account, none is chosen. Measured on the samples, this costs recall but keeps step precision at 1.000.

## Results

Development set (32 samples): status accuracy 1.000, step precision 1.000, step recall 0.902, false-COMPLETE rate 0.000. Details, the failure list, the ablation study and 16 independent test cases are in [`code/evaluation/evaluation_report.md`](code/evaluation/evaluation_report.md).

## Known limitations

- 142 deletion cases carry no account step: their account is linked only by a non-unique workflow match.
- Already-anonymized analytics rows that carry no identifier are not attributed.
- OCR misses some screenshot rows. Two screens show no resource ids at all.

## Security and data handling

- No secrets in code, config or logs. `.env` is git-ignored, and `.env.example` documents the only variable.
- Evidence text is treated as data. Nothing extracted from files is executed or followed as an instruction.
- `code.zip` excludes `dataset/`, virtual environments, caches and run artefacts:

```bash
zip -r code.zip README.md code -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "code/run/*" "*/.DS_Store"
```
