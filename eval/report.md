# Agent Orchestrator — Eval Report

_Generated: 2026-06-07T20:10:51+00:00 · mode: **offline / deterministic** (no Ollama)._

## Summary

- **Tasks:** 10
- **Passed:** 10 / 10 (**100%** success rate)
- **Total tool calls executed:** 10
- **Human-in-the-loop escalations:** 1
- **Latency:** mean 486 ms · median 8 ms · max 2452 ms

## Per-task results

| Task | Status | Tools | Latency | Escalation | Result |
|---|---|---|---|---|---|
| ✅ `calc_multiply` — Calcul direct (multiplication) | completed | 1 | 0 ms | — | ✅ |
| ✅ `calc_tax_rate` — Calcul d'un taux (30%) | completed | 1 | 16 ms | — | ✅ |
| ✅ `calc_quotient` — Division (parts de quotient familial) | completed | 1 | 0 ms | — | ✅ |
| ✅ `list_dir` — Lister un dossier (list_files) | completed | 1 | 0 ms | — | ✅ |
| ✅ `read_doc` — Lire un fichier (read_file) | completed | 1 | 0 ms | — | ✅ |
| ✅ `search_pattern` — Rechercher un motif (search_text) | completed | 1 | 15 ms | — | ✅ |
| ✅ `rag_offline_safe` — Outil RAG fiscal — dégradation propre hors-ligne | completed | 1 | 2452 ms | — | ✅ |
| ✅ `multi_step` — Plan multi-étapes (calculator + rag_fiscal) | completed | 2 | 2359 ms | — | ✅ |
| ✅ `high_risk_escalation` — Escalade humaine sur outil à risque élevé | approval_required | 0 | 0 ms | ⚠️ yes | ✅ |
| ✅ `high_risk_approved` — Exécution après approbation humaine | completed | 1 | 15 ms | — | ✅ |

## What this measures

- **Tool routing** — the planner's tool calls are dispatched and executed.
- **Numeric correctness** — `calculator` results are checked against expected values.
- **Offline safety** — `rag_fiscal` degrades gracefully when the RAG API is down.
- **Human-in-the-loop** — HIGH-risk tools escalate to `approval_required` and are **not** executed; after approval they run and the task completes.
- **Observability** — every step is a trace span with latency.
