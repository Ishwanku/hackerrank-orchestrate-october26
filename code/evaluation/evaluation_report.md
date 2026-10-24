# Evaluation Report — Ghost Data Still Exists

All numbers below come from running the code in this repository (commands in each section). The 32 public samples are a **development set** that the rules were studied against, so they are not an unbiased estimate of hidden-test accuracy. The independent tests in section 4 were written from the specification, not from the samples.

## 1. Headline metrics (32 sample cases)

Command: `python3 code/main.py --sample && python3 code/evaluation/score.py`

| Metric | Value | Definition |
| --- | --- | --- |
| Case-level status accuracy | **1.000** (32/32) | `deletion_status` equals the reference |
| Row accuracy (exact case match) | 0.469 (15/32) | whole `steps_json` array identical, order included |
| Step precision | **1.000** (174/174) | predicted steps that appear in the reference (all 7 fields except `step_no`) |
| Step recall | 0.902 (174/193) | reference steps that were produced |
| Step F1 | 0.948 | |
| Field accuracy — `state` on matched steps | 1.000 | steps matched on phase+operation+system+resource |
| Field accuracy — `evidence_id` on matched steps | 1.000 | same matching |
| Sequence accuracy | 1.000 | cases whose step *set* is right are also in the right order |
| False-COMPLETE rate | **0.000** | predicted COMPLETE where the reference is INCOMPLETE (the costliest privacy error) |

Full run (518 cases): `python3 code/main.py` → 352 INCOMPLETE, 156 COMPLETE, 10 NOT_APPLICABLE; 3,031 steps; validator 0 errors. Three consecutive runs produced byte-identical `output.csv` (sha256 prefix `6e8f0b11d5866e75`).

## 2. Remaining failures (all 19 missing steps, 0 wrong steps)

Command: `python3 code/evaluation/diff.py`

| Missing step type | Count | Cases | Root cause |
| --- | --- | --- | --- |
| `VERIFY_RECORD_ABSENT` on an account | 10 | 04, 06, 07, 08, 10, 22, 23, 28, 29, 30 | The account has no identifier in any participant-visible file. Five (`account_00N`) are hand-made sample records whose only link is an activity note of a different template; five are workflow matches that are **not unique** (several requests share the reported day and status), so the system deliberately leaves them unattributed. |
| `VERIFY_RECORD_ANONYMIZED` on analytics | 7 | 03, 04, 21, 25, 26, 27, 28 | Already-anonymized analytics rows carry no identifier anywhere; only a same-day "policy action completed" activity exists. No specification-supported rule ties them to a person, so they are not attributed. |
| `VERIFY_RECORD_PRESENT` on an audit record | 2 | 18, 20 | `audit_record_6645` / `audit_record_5569` occur in no evidence file, log, image or PDF. |

Every remaining failure is a **missing** verification step for a resource the visible evidence does not tie to the person. No predicted step is wrong.

## 3. Failures found during development and the fixes made

Each line is a measured change on the sample set (status accuracy / step precision / step recall).

| # | Failure found | Fix | Before → after |
| --- | --- | --- | --- |
| 1 | Keyword intent marked 5 deletion follow-ups ("check the profile is gone") as NOT_APPLICABLE, and "copy of my profile" matched an export cue | Only an explicit non-deletion purpose (correction, export, access, opt-out, login help, negated deletion) makes a case NOT_APPLICABLE | 0.781 / 0.940 / 0.736 → 0.875 / 0.931 / 0.845 |
| 2 | Inventory captures treated as complete listings made present records look deleted | Listings prove absence only for the people the capture covers; full topology dumps stay complete | → 0.875 / 0.937 / 0.850 |
| 3 | A copy surviving on a failover replica lost to the primary because row `updated_at` values differed | All tables of one topology capture are read at the capture time, and any surviving copy wins | 0.875 → 0.938 status |
| 4 | Support items the workflow tried to DELETE were planned as REDACT | Workflow's own action reveals the category (attachment vs message) | (part of 3) |
| 5 | Old 404 lookups and catalog notes from an earlier account lifecycle were linked to the new request | Links seen only before `requested_at` that never showed the record present are dropped (3 wrong dropped, 0 right) | 0.938 / 0.955 / 0.886 → 0.969 / 0.989 / 0.912 |
| 6 | A hash-keyed contact-list row (opt-in flag) needed DELETE, not ANONYMIZE | Classified as SECONDARY_IDENTIFIER (rule_02) | (part of 5) |
| 7 | **ID-order tie-breaking** among same-day/same-status accounts was right at chance level — unsupported identity claims | Removed. Only unique matches are attributed, labelled `inferred:workflow-unique` | 0.969 / 0.989 / 0.912 → 0.969 / 1.000 / 0.886 |
| 8 | OCR-only perception missed the PDF attachment record and most console rows | Deterministic pdftotext + OCR extraction with page-level rules and closed-world email snapping | 0.969 / 1.000 / 0.886 → 1.000 / 1.000 / 0.902 |

Fix 7 lowered recall on purpose: it trades 5 correct but lucky guesses for zero unsupported links. The 120 accounts still attributed by workflow in the full run all come from unique matches.

## 4. Additional evaluation cases (independent of the samples)

Command: `python3 -m unittest discover -s code/tests -v` → **16 tests, all pass.** Each test builds a small synthetic dataset and runs the real pipeline and validator.

| # | Case | Expected result | Why the evidence supports it |
| --- | --- | --- | --- |
| 1 | Two requests, same reported day and status, two unowned account deletions | No account attributed to either; both listed as unresolved | A non-unique date/status match does not establish identity |
| 2 | One request, one unowned FAILED account deletion on the reported day, full-table dump without it | COMPLETE; `VERIFY_RECORD_ABSENT` citing the dump; trail says `inferred:workflow-unique` | Unique timestamp + status link; absence proven by a complete listing |
| 3 | Request uses the **old** email; a search document holds only the SHA-256 of that old email | INCOMPLETE; `REPORT_REMAINING_RECORD search_5` | Audit-log history + hash closure |
| 4 | Bundle with an empty account collection covering **another** person | Account still reported as remaining | A partial snapshot cannot prove absence for people it does not cover |
| 5 | Same bundle covering the requester | COMPLETE; absence cites the bundle | Covered subject |
| 6 | Account gone from primary, alive on failover replica | `REPORT_REMAINING_RECORD` citing the replica capture | Replication drift: a surviving copy is still data |
| 7 | Present at 09-10, "deleted" in a capture dated after `audit_at` | INCOMPLETE; later file never cited | Only information at or before `audit_at` counts |
| 8 | Workflow claims DELETE SUCCESS; a later read-back returns HTTP 200 | `REPORT_REMAINING_RECORD` | Claims never override observations |
| 9 | Log line with a non-ISO timestamp | Line ignored | No guessing of malformed times |
| 10 | Tombstone still showing the email | `REPORT_EXPOSED_PII` → `REDACT_RECORD` → `VERIFY_RECORD_REDACTED`; never DELETE | rule_15 keeps the stable `user_id` only |
| 11 | Clean tombstone + audit record in retention | COMPLETE; `VERIFY_RECORD_PRESENT` + `VERIFY_RECORD_REDACTED` | rule_12 RETAIN, rule_15 REDACT |
| 12 | Enabled connector + restorable backup + remaining search entry | Remediation order DISABLE_DATA_FLOW → BLOCK_RESTORE → DELETE_RECORD | Stop recreation paths before changing records |
| 13 | Analytics row still holding the email | INCOMPLETE; ANONYMIZE (not DELETE) | rule_07 |
| 14 | "Send me a copy … please don't delete anything" | NOT_APPLICABLE, `[]` | Negated deletion is not authorisation |
| 15 | Real PDF `delivery_correction_attachment.pdf` | `support_001` linked to its customer's email | Single-record document rule |
| 16 | Output citing an evidence id that does not exist | Validator rejects it | Evidence must be participant-visible |

## 5. Ablation study (one component off at a time, sample set)

Command: `python3 code/evaluation/ablation.py`

| Variant | Status acc. | Step P | Step R | Step F1 | False-COMPLETE |
| --- | --- | --- | --- | --- | --- |
| full system | 1.000 | 1.000 | 0.902 | 0.948 | 0.000 |
| no workflow attribution | 1.000 | 1.000 | 0.860 | 0.925 | 0.000 |
| no identity history (audit log) | 0.938 | 0.988 | 0.819 | 0.895 | 0.091 |
| snapshots treated as complete listings | 0.969 | 0.941 | 0.829 | 0.882 | 0.045 |
| no pre-request stale-link filter | 1.000 | 0.983 | 0.902 | 0.941 | 0.000 |
| no PDF/screenshot perception | 0.969 | 1.000 | 0.886 | 0.940 | 0.045 |

Every component improves at least one metric; identity history and subject-scoped snapshots matter most.

## 6. Correct versus merely valid

A syntactically valid file can still be wrong. The validator (`code/ghostaudit/validate.py`) only guarantees the contract: header, row order, legal (phase, operation, state) triples, ordering, step numbering, evidence existence and capture time ≤ `audit_at`, empty evidence on future steps, and never deleting retained records, backups or tombstones. Correctness is measured separately against reference answers (sections 1–2) and against independently constructed cases (section 4).

## 7. Known limits

- **142 of 508 deletion cases have no account step**, because the visible evidence does not tie the account to the person uniquely. On the samples this lowers recall but never precision.
- Screenshot reading is deterministic OCR. It does not recover `audit_record_002` from the security console, and two screens show no resource ids at all. An optional vision-LLM backend exists (`perception/extract.py --backend anthropic`) but was **not** used for this output; see `usage_report.md`.
- The legal-retention register PDF lists orders and user ids but no resource ids that match any hold record, so it adds no resources.
