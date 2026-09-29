# Jev: QA harness for the DT desktop app (instructions for coding agents)

This repository is a test harness, not the product. It launches the DT app (the PySide6 desktop
app in the sibling `DT` repository) in a sandbox and lets you, or OpenRouter-hosted models, use it
like a person to find user-experience problems, bugs and edge cases. Claude Code reads this file
through `CLAUDE.md`; Codex reads it directly.

## Setup check (do this first)

```bash
jev doctor            # DT checkout, Qt offscreen start, FFmpeg, OPENROUTER_API_KEY
jev doctor --online   # also checks OpenRouter reachability and the key
```

If `jev` is not on PATH, use `python -m jev ...` from this repository. `JEV_DT_PATH` points at the
DT checkout (default `../DT`); `JEV_PYTHON` at an interpreter with DT's desktop extra installed
(default: DT's `.venv`, else the current interpreter).

## Ways to test

1. **Jev drives everything and builds the improvement dataset** (no model cost unless a budget is given):
   - `jev campaign` runs DT's own tests (read-only, under coverage), the scripted sweep of every
     feature, `jev verify` on known issues, seeded crawlers, and then `jev dataset build`.
     `--budget 2` adds OpenRouter testers on core and coverage-gap missions (needs the key).
   - Pieces on their own: `jev sweep`, `jev scenario run <name>`, `jev crawl --steps 300`,
     `jev verify [--issue JEV-0003]`, `jev minimise JEV-0102`, `jev dataset build`.
   - Results: `dataset/improvements.md` (ranked backlog), `dataset/handoff/` (fix briefs for DT),
     `dataset/registry.json` (issues with stable IDs and status). `jev issues`, `jev issues show ID`.
2. **You drive the app** with the `jev` MCP tools (`.mcp.json` registers them for Claude Code; see
   README for Codex) or with the CLI, which prints the same text:
   - `jev start --seed sample` starts a detached app with three synthetic assessments
     (`--seed none` = first-run unlock screen, `empty` = unlocked empty vault; `--network mock` fakes
     the AI/NHVR/FFmpeg services; `--screen 1024x768`; `--idle-timeout-ms 45000`).
   - `jev snapshot` lists every control with a ref such as `w12`. Act with refs or visible labels:
     `jev click w12`, `jev type "Driver name" "sam synthetic" --submit tab`, `jev select "Licence class" HC`,
     `jev item list "Riley Ready"`, `jev tab "4 Finalise"`, `jev key Tab`, `jev draw "Signature drawing area"`,
     `jev wait 5 --until idle`, `jev screenshot --marks --out shot.png`, `jev audit`, `jev network`.
   - Every action result says what happened (dialogs, status bar messages, network attempts) and
     includes a fresh snapshot. `jev report-issue ...` records a finding with evidence.
   - `jev stop` when done. Output lives in `runs/cli-<name>-<time>/`.
3. **OpenRouter testers drive the app** autonomously (needs `OPENROUTER_API_KEY`):
   - `jev run --model x-ai/grok-4.7 --mission first-run --persona new-trainer`
   - `jev matrix --models trio --missions first-run,assess-marking --personas new-trainer,edge-case-hunter --parallel 3 --max-cost 1`
   - `jev missions`, `jev personas`, `jev models --tools` list the choices. Each run writes
     `report.md`, `findings.jsonl`, `transcript.jsonl` and `evidence/` under `runs/`.

## Rules

- Synthetic data only. Never open a real vault, never point Jev at a folder outside its sandbox.
- Keep `--network block` (default) or `mock`. Use `allow` only when the user explicitly asks for a
  live provider test, and say which host will be contacted.
- OpenRouter runs cost money. Always pass `--max-cost` and a modest `--max-steps` unless the user
  gave a budget. Report the cost from `run.json` / `summary.md`.
- Do not change the DT repository while testing. If asked to fix bugs, do it in DT on a branch,
  and add a regression test there.

## Triage workflow (after a run, matrix or campaign)

1. Run `jev dataset build`, then read `dataset/improvements.md` and `jev issues`. Findings from all
   runs are merged into issues with IDs (`JEV-####`). For one run, `runs/<run>/report.md` or
   `runs/matrix-*/summary.md` also work.
2. For each finding, reproduce it yourself with the CLI or MCP tools using its steps. Reading the
   DT source (`../DT/src/dt/ui.py` and friends) helps confirm the cause.
3. Classify: **confirmed bug**, **UX issue**, **by design** (documented in DT's README), **known
   limitation** (DT README "Not implemented"/"Known limitations"), or **harness artefact**
   (offscreen rendering, the stand-in file chooser, blocked network, missing audio/GPU).
4. Record each decision: `jev issues set JEV-0105 --status by-design --note "README says ..."`
   (or `--classification "ux issue"`, `--duplicate-of JEV-0003`). The MCP `set_issue` tool does the same.
5. Write the final QA report: confirmed items first, each with minimal repro steps, expected vs
   actual, evidence path, suspected code location, and severity. The handoff briefs in
   `dataset/handoff/issues/` already contain most of this.

Harness findings (source `harness`) come from automatic detection: unhandled Python exceptions
(with traceback), interface freezes (with the frozen stack), crashes (fault log), and technical
error text shown to users. Treat an exception or crash as high priority until disproved.

## Fixing DT issues (only when asked)

Work in the DT repository on a branch, add a DT regression test, then from this repository run
`JEV_DT_PATH=<that DT checkout> jev verify --issue JEV-XXXX`. A passing replay marks the issue fixed
against that DT commit; if it comes back later it is marked regressed. Never edit DT from a Jev run.

## Layout

- `jev/host/` runs inside the app process: widget snapshots (`describe.py`), input (`actions.py`),
  sandbox guards and the stand-in file chooser (`guards.py`), event monitors, control server.
- `jev/session.py` starts/stops one sandboxed app; `jev/tools.py` is the tool set shared by MCP and
  the OpenRouter agent; `jev/agent/` is the OpenRouter loop; `jev/data/` holds the app primer,
  missions and personas (plain Markdown; add your own or pass a path to `--mission`/`--persona`).
- `jev/data/scenarios/sweep/` and `regressions/` hold JSON scenarios. A regression scenario's `issue`
  block (with its `JEV-####` ID) seeds the registry. When you confirm a new bug, add a regression
  scenario that checks the correct behaviour; `jev scenario record <run> --until <step>` gives a start.
- `jev/scenarios.py`, `jev/crawler.py`, `jev/campaign.py`, `jev/dataset.py`, `jev/registry.py`,
  `jev/verify.py`, `jev/triage.py`, `jev/dtsource.py`: see docs/dataset.md.
- Tests: `python -m unittest discover -s tests` (integration tests start the real app offscreen).
