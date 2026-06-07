# Demo Script — Local Agent Orchestrator (< 3 min)

**Goal:** show a recruiter that this is an *agent runtime* — plan → tools →
human approval → result → trace — running locally, in under three minutes.

**Pitch (one line, say it up front):**
> "This isn't a chatbot — it's the orchestration layer under an agent product:
> it plans a task, runs tools, stops high-risk actions for human approval, and
> records everything as an inspectable trace. It runs fully offline."

---

## Pre-flight (before recording)

```bash
# Terminal 1 — API on :8100  (FORCE_FALLBACK makes it 100% offline)
cd 7-Agent-Local
$env:PYTHONPATH = "src"; $env:FORCE_FALLBACK = "true"
uv run --no-sync uvicorn agent.api.main:app --port 8100

# Terminal 2 — UI on :3000
cd 7-Agent-Local/frontend
npm run dev
```

Open `http://localhost:3000`. Pick light or dark up front (toggle is top-right).
Have one completed run already in the list so the table isn't empty.

---

## Scene 1 — The pitch + the runs list  (0:00 – 0:25)

- Land on **`/runs`**. Say the one-line pitch.
- Gesture at the **health badge** (top-right): "API online, and it'll show
  Ollama online/offline — right now it's running offline with a deterministic
  fallback, no cloud, no quota."
- "Each row is a past run with a colour-coded status. Let's launch one."

## Scene 2 — Launch a task  (0:25 – 0:50)

- Click **New run**. The dialog opens.
- Click a **suggestion chip** (e.g. *"Quel est le plafond du quotient familial ?"*),
  mention **⌘↵** to submit. Click **Lancer**.
- A toast confirms "Run lancé"; you're routed to the run detail page.

## Scene 3 — Plan → tools → result, live  (0:50 – 1:30)

- On the detail page, point out the **header**: the task, the status badge, and
  the metrics (total latency, number of tool calls).
- **Tabs:** open **Plan** — "the supervisor decomposed the task into subtasks and
  picked the tools." Open **Result** — "here's the synthesised answer and the raw
  tool output, with a copy button."
- Open the **Trace** tab — "every step is a span: `intake → plan → tool:rag_fiscal
  → write → review`, each with its latency. Click a span to expand its JSON
  payload." Expand the `tool:` span. "Full observability — you see exactly what
  the agent did."

## Scene 4 — Human-in-the-loop (the money shot)  (1:30 – 2:20)

- Launch a **HIGH-risk task** (CLI is fastest, or a pre-seeded run):
  ```bash
  uv run --no-sync agent run "Supprime le fichier obsolete.txt"
  ```
  Then open that run in the UI (or have it ready).
- The status is **`approval_required`**. The **amber approval panel** shows the
  reason and the HIGH-risk tool (`delete_file`) as a badge.
- "The graph **refused to execute** the high-risk tool — not because the prompt
  said so, but because the gate is built into the runtime. It's waiting for a human."
- Click **Approuver**. Toast fires; the run re-executes and flips to **completed**.
  "Now — and only now — the tool ran."
- *(Optional)* Click **Rejeter** on another run to show it lands in `failed`.

## Scene 5 — It's tested and measured  (2:20 – 2:50)

- Cut to a terminal:
  ```bash
  uv run --no-sync pytest -q            # 81 passed — zero model calls
  uv run --no-sync python eval/run_eval.py
  ```
- "81 tests, none of them touch a real model. And a 10-task golden set runs the
  real pipeline offline: **10/10**, with the high-risk escalation verified
  end-to-end. Orchestration overhead is sub-millisecond."
- Show `eval/report.md` briefly.

## Close  (2:50 – 3:00)

> "Local-first, fully observable, human-in-the-loop, and quota-free to run and
> test. The companion RAG project is plugged in here as just one tool — this is
> the platform that orchestrates it."

---

## Timing cheat-sheet

| Scene | Budget | Running |
|---|---|---|
| 1 — Pitch + runs list | 0:25 | 0:25 |
| 2 — Launch a task | 0:25 | 0:50 |
| 3 — Plan/tools/result/trace | 0:40 | 1:30 |
| 4 — Approval flow | 0:50 | 2:20 |
| 5 — Tests + eval | 0:30 | 2:50 |
| Close | 0:10 | 3:00 |

## Tips

- Pre-seed 2–3 runs (one completed, one `approval_required`, optionally one
  `failed`) so every status colour is visible without waiting.
- Record light and dark variants of the key screens for the README gallery.
- If Ollama *is* running, you can drop `FORCE_FALLBACK` to show real planning —
  but the demo is stronger when you stress that it works **without** it.
