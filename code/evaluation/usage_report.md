# Usage Report — final full-dataset run

## Summary

The run that produced `output.csv` made **zero model calls**. Every decision is computed by deterministic Python, from the CSV/JSON/SQL/log evidence plus a committed cache of facts extracted from the 4 PDFs and 11 screenshots. That cache was also built without a model, using `pdftotext` and `tesseract` (`--backend local`).

| Item | Value |
| --- | --- |
| Command | `python3 code/main.py` |
| Requests processed | 518 |
| Wall-clock time | 0.39–0.44 s (three runs; Python 3.13, cloud Linux container) |
| Output determinism | 3 runs, byte-identical `output.csv` (sha256 prefix `6e8f0b11d5866e75`) |
| External network calls | 0 |

## Model usage

| Provider | Model | Model calls | Input tokens | Output tokens | Total tokens | Avg tokens / request | Estimated cost | Cost / request |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — (none) | — | 0 | 0 | 0 | 0 | 0 | USD 0.00 | USD 0.00 |
| **Overall** | | **0** | **0** | **0** | **0** | **0** | **USD 0.00** | **USD 0.00** |

These are measured values, not estimates. No model API was configured or called during development runs or during the final run.

## Perception cache (one-time step)

| Step | Tool | Files | Model calls | Tokens |
| --- | --- | --- | --- | --- |
| PDF text extraction | `pdftotext` (poppler) | 4 | 0 | 0 |
| Screenshot OCR | `tesseract` | 11 | 0 | 0 |

Rebuild with `python3 code/ghostaudit/perception/extract.py --force`. Without these tools, the committed `code/cache/*.json` files are used as-is.

## Optional vision backend (not used for this output)

`perception/extract.py --backend anthropic` can replace OCR with a vision model. It reads `ANTHROPIC_API_KEY` from the environment or a git-ignored `.env`, sends one request per binary file (15 files), and appends the real `usage.input_tokens` / `usage.output_tokens` from each API response to `code/cache/usage_log.jsonl`. If it is ever used, this report must be regenerated from that log. It currently does not exist, because no call was made.

For planning only, here is what such a run would cost (not a measurement). With `claude-sonnet-5-5`, priced at USD 2 per million input tokens and USD 10 per million output tokens per [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) (checked 2026-10-24), 15 calls would likely cost well under USD 1.

## Why there are no LLM calls

The task is exhaustive search plus exact policy application over structured records. Code guarantees exact resource ids, the official ordering, evidence that predates `audit_at`, and identical reruns. An LLM is useful only for reading pixels, and deterministic OCR plus closed-world validation covered the facts that mattered on the development set (see `evaluation_report.md`, ablation table).
