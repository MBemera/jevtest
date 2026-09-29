# Jev: AI QA harness for the DT desktop app

Jev lets AI testers use [DT](../DT) the way a trainer would, looking for user-experience problems,
bugs and edge cases. DT is the offline PySide6 driver-training and assessment app. The testers can
be Claude Code, Codex, or any tool-calling model on OpenRouter.

- DT runs unchanged in its own process, offscreen, inside a disposable sandbox with synthetic data.
- The harness turns the live Qt widget tree into a compact text **snapshot**. Every control gets a
  stable ref such as `w12`, with its role, label, value and state.
- **Actions** are real mouse and keyboard events. An action cannot touch a control that is hidden,
  disabled or behind a modal dialog, and neither could a person.
- Every result reports **what happened**: dialogs opening and closing, status bar messages, network
  attempts and sandbox refusals. The harness also flags these problems itself:
  - unhandled Python exceptions, with the traceback
  - interface freezes, with the stack of the frozen thread
  - crashes, with the fault log
  - technical error text shown to users
- Findings come with evidence: a screenshot, a snapshot and recent events. Findings from several
  runs and models are merged into one report.
- Besides AI testers, Jev drives DT itself: a **scripted sweep** of every feature, **regression
  scenarios** for known issues, a seeded **crawler** that uses every reachable control with
  edge-case input, and DT's **own test suites**. Every run records its steps and which DT code ran.
- `jev dataset build` turns all runs into an **improvement dataset for DT**: a registry of issues with
  stable IDs, a ranked backlog, fix briefs with code locations, and coverage of DT's screens and code.
  `jev verify` replays each issue on a DT checkout and marks it fixed or regressed.

```
 Claude Code / Codex ──MCP (stdio)──┐                  ┌──────────── app process ─────────────┐
 jev CLI (any agent's shell) ───────┤                  │ control server → Qt GUI thread        │
 jev run / matrix (OpenRouter) ─────┼─> tools.py ──TCP─┤ snapshot · actions · monitors · guards│
 jev sweep / scenario / crawl ──────┘   steps.jsonl     │ coverage probe                        │
        │                               findings        │ DT: dt.ui.main() unchanged, offscreen │
        │                                               └───────────────────────────────────────┘
 jev campaign ── runs all of the above + DT's own tests ──> jev dataset build ──> registry, backlog,
                                                            jev verify               handoff for DT
```

## Install

You need Python 3.11+ and a DT checkout next to this repository (`../DT`), or set `JEV_DT_PATH`.
Install everything into one virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e "../DT[desktop]" -e .
jev doctor                           # checks DT, Qt offscreen start, FFmpeg, OpenRouter key
```

- **Linux** also needs the Qt system libraries DT lists:
  `libegl1 libopengl0 libxkbcommon0 libpulse0 libgstreamer1.0-0 libgstreamer-plugins-base1.0-0`.
- **FFmpeg** on PATH (or DT's own install) enables the video fixtures and DT's media features.
- **OpenRouter:** put `OPENROUTER_API_KEY` in the environment or in a `.env` file (see
  `.env.example`). It is only needed for `jev run` and `jev matrix`.

If DT already has its own `.venv`, Jev uses it for the app process automatically. You can also
set `JEV_PYTHON` to that interpreter.

## Run everything and build the improvement dataset

```bash
jev campaign                          # ~20 min, no model cost: DT tests, sweep, verify, 2 crawls, dataset
jev campaign --budget 3 --models auto:3   # adds OpenRouter testers on core and coverage-gap missions
jev dataset show                      # what the dataset says now
jev issues                            # open issues, highest priority first
jev issues show JEV-0003              # the fix brief: repro steps, evidence, code locations
```

A campaign runs these stages and records each in `runs/campaign-*/report.md`:

| Stage | What it does |
| --- | --- |
| dt-tests | DT's unit and desktop suites under coverage. Read-only: DT's git status is compared before and after |
| sweep | 16 scripted journeys through every feature (`jev/data/scenarios/sweep/`), with soft checks on known issues |
| verify | replays the scenario of every known issue: still open, fixed, or regressed |
| crawl | seeded crawlers starting from sample records, the first-run screen and an empty vault |
| minimise | shrinks the replays of new harness-detected issues (exceptions, crashes, freezes, leaked error text) to the few steps that still trigger them |
| ai-testers | only with `--budget` and a key: OpenRouter testers on core missions plus missions written from coverage gaps, each run capped at its share of the budget |
| dataset | rebuilds the dataset, backlog and DT handoff |

The dataset (default `dataset/` next to `runs/`, or `$JEV_DATASET_DIR`) holds:

- `improvements.md`: one ranked backlog. It lists issues first, then code no run has executed,
  labels DT defines that never appeared on screen, unlabelled controls, wording problems, mixed
  terminology and slow actions.
- `handoff/`: what DT's developers (or a coding agent in the DT repo) work from. It has a brief per
  open issue with repro steps, expected and actual behaviour, screenshots, code locations with
  excerpts, a replayable scenario and a definition of done. `handoff/issues.json` has the same data.
- `registry.json`: issues keep their `JEV-####` ID across builds, with a status history tied to
  DT commits. Known issues shipped with Jev are `JEV-0001` to `JEV-0100`; discovered ones start at
  `JEV-0101`. Share or commit this file to keep IDs stable across machines.
- `jev-dataset.sqlite` plus CSV/JSONL copies. Tables: runs, every step, findings, issues, UI
  controls, per-function code coverage (Jev runs vs DT's own tests), copy checks, every typed input
  with DT's reaction, and latency. [docs/dataset.md](docs/dataset.md) describes each table.

The fix loop for DT:

```bash
jev issues show JEV-0003                                  # read the brief
# fix it in DT on a branch, add a DT regression test
JEV_DT_PATH=/path/to/DT-branch jev verify --issue JEV-0003  # replay: passes -> marked fixed with the commit
jev campaign                                              # later runs mark it regressed if it comes back
```

`jev dataset export --to <folder>` writes a shareable copy for DT's team: the backlog, briefs,
replays and one screenshot per issue, without raw runs or local paths.
[docs/baseline/](docs/baseline/README.md) is such a copy, from a campaign against DT `6ead556`.

`jev issues set JEV-0105 --status by-design --note "..."` records a triage decision.
`jev triage --max-cost 0.25` optionally asks a cheap OpenRouter model to classify unconfirmed
issues. It only routes to providers that do not store prompts, records its reasoning, and
changes an issue only when confident.

## Scripted checks and the crawler (no model needed)

```bash
jev sweep                             # every feature, scripted, ~8 min; summary in runs/sweep-*/summary.md
jev scenario list                     # sweep/ and regressions/ scenarios
jev scenario run regressions/cancel-report-request
jev scenario record runs/<run> --out my-journey.json   # turn any recorded run into a replayable scenario
jev crawl --steps 300 --random-seed 7 --seed none      # explore from the first-run screen
jev minimise JEV-0102                 # shrink an issue's replay to the steps that still trigger it
```

A scenario is JSON: a list of steps (`{"do": "click", "target": "Save", "expect": {"dialog":
"Saved"}}`) using labels rather than refs, so it survives DT layout changes. Expectations can
check dialogs, messages, status text, screen contents, values, network use and uncaught
exceptions (always checked). A failed expectation is recorded as a finding with evidence. The
crawler weighs never-used controls first, types edge-case text (empty, very long, Unicode, markup,
SQL-like, paths, bad dates), picks every tab, row and option, handles dialogs and restarts DT after
a crash. The same `--random-seed` replays the same journey on the same DT build, and each finding
gets a replay scenario. `jev minimise` (and the campaign's minimise stage) then replays shorter and
shorter versions (delta debugging) and keeps the shortest one that still produces the same
signature, so a crawler bug found after 150 steps usually ends up as a repro of 2 to 5 steps.

## Drive the app yourself (CLI)

```bash
jev start --seed sample          # detached app; sample = unlocked vault with 3 synthetic assessments
jev snapshot                     # what is on screen, with refs
jev item list "Riley Ready"      # click a row in the assessments list
jev tab "4 Finalise"
jev click "Sign assessment"
jev draw "Signature drawing area"
jev click Save
jev screenshot --marks --out signed.png
jev audit                        # clipped text, sideways scrolling, overlaps, unlabelled controls, tab order
jev report-issue --title "..." --severity medium --category ux --steps "1. ..." --expected "..." --actual "..."
jev stop
```

Targets are refs from the latest snapshot (`w12`) or visible labels (`"Save preparation"`). Every
action prints what happened, then a fresh snapshot. `jev stop` writes the session's `report.md`.
[docs/example-report.md](docs/example-report.md) shows the output from a short session that
found four real DT issues.

`jev start` options:

| Option | Values |
| --- | --- |
| `--seed` | `none` (first-run unlock screen), `empty`, `sample` |
| `--network` | `block` (default), `mock`, `allow` |
| `--screen` | `1366x768` (default), `1024x768`, `2560x1440@2`, ... |
| `--idle-timeout-ms` | shortens DT's 5-minute idle lock |
| `--ffmpeg` | `none` hides FFmpeg from DT |
| `--visible` | shows real windows so you can watch |

## Use it from Claude Code

This repository ships `.mcp.json`, which registers the `jev` MCP server, plus `/qa` and
`/campaign` commands and a `dt-qa` skill. Open Claude Code in this folder and approve the server.
Then ask, for example, "QA the evidence import flow", run `/qa evidence-media edge-case-hunter`,
or run `/campaign` to have Jev exercise all of DT and triage the resulting dataset.

To make the server available in every project instead, see `examples/claude-code-user-scope.sh`.

## Use it from Codex

Codex reads `AGENTS.md` automatically. It can use the CLI above from its shell. For native tools,
add the MCP server from `examples/codex-config.toml` to `~/.codex/config.toml` with absolute paths.

## Autonomous testers on OpenRouter

```bash
jev models --tools --vision                               # what your key can use today
jev run --model x-ai/grok-4.7 --mission first-run --persona new-trainer --max-cost 0.50
jev matrix --models trio --missions first-run,evidence-media,finalise-sign-export \
           --personas new-trainer,edge-case-hunter --parallel 3 --max-steps 60 --max-cost 1
jev report runs/matrix-*/ --out qa-report.md             # merge any runs into one report
```

`jev matrix` gives every combination its own app and sandbox. The merged `summary.md` groups
duplicate findings and shows which models found each one, so you can compare models.

- **Models:** model presets live in `jev/data/model_presets.json`. The `trio` preset uses three
  models confirmed on OpenRouter on 2026-09-27. Model IDs change, so check `jev models --tools`.
- **Screenshots:** vision-capable models are sent them automatically (`--vision auto`).
- **Stop conditions:** each run stops when it hits its step budget, `--max-cost`, `--max-minutes`,
  or when the tester calls `finish`.

Each run writes these files to `runs/<run>/`:

| File | Contents |
| --- | --- |
| `report.md` | findings, steps and evidence |
| `findings.jsonl` | one finding per line |
| `transcript.jsonl` | every model reply and tool call |
| `run.json` | cost, tokens, duration and stop reason |
| `evidence/` | screenshots, snapshots and events per finding |
| `app/` | app logs, events and recorded network requests |

From Claude Code or Codex, the `run_qa_agents` MCP tool starts the same matrix in the background,
and `qa_runs` shows its progress and reports.

### Missions and personas

`jev missions` and `jev personas` list them; each is a short Markdown file in `jev/data/`. You
can pass your own file path to `--mission` or `--persona`, or a sentence of free text.

| Missions | Personas |
| --- | --- |
| first-run, prepare-assessment, assess-marking, evidence-media, finalise-sign-export, lock-backup-recovery, business-directory, module-builder, ai-report-drafting, registration-check, small-screen-keyboard, explore | new-trainer, busy-assessor, edge-case-hunter, accessibility-auditor, security-privacy-reviewer, domain-assessor |

A mission's front matter picks the starting state, for example `seed: sample`,
`network: mock`, `screen: 1024x768` or `idle_timeout_ms: 45000`.

## Tools

These tools are shared by MCP and the OpenRouter agent; the CLI has the same commands.

| Tool | What it does |
| --- | --- |
| `snapshot` | windows, dialogs, controls with refs, values, states, status bar |
| `click`, `type_text`, `select_option`, `set_checked`, `select_item`, `select_tab`, `press_key`, `draw`, `scroll`, `set_value`, `resize_window`, `close_window` | real input; the result includes what happened and a new snapshot. `scroll` turns the wheel with the pointer over the target, so a dropdown under the pointer changes value, as it would for a person |
| `wait` | let background jobs finish (`until=idle`) |
| `screenshot` | PNG of the screen or one widget; `marks=true` labels refs |
| `read_text`, `list_items` | full text of long labels, text areas, lists and dropdowns |
| `audit` | layout and accessibility heuristics plus tab order |
| `events`, `network_log` | observed events; exact payloads DT tried to send |
| `set_network_mock` | mock answers: ok, slow, timeout, http_401/403/429/500, unfinished, empty, oversized, invalid_json, injection, long_draft, not_found, multiple, different_plate |
| `sandbox_info` | sandbox folders, fixture files, seeded vault passphrase |
| `restart_app` | restart (keeps the sandbox unless `fresh`); tests persistence and recovers from crashes |
| `report_issue` | record a finding; a screenshot, snapshot and events are attached |
| `note`, `finish` | OpenRouter agent only |
| `app_start`, `app_stop`, `findings`, `run_qa_agents`, `qa_runs` | MCP only |
| `run_campaign`, `campaign_status`, `dataset`, `issues`, `set_issue`, `verify_issues` | MCP only: campaigns in the background, the dataset, the issue registry and verification |

## Sandbox and safety

- **Folders:** each session has a sandbox under `runs/` with `vaults/`, `exports/`, `backups/`,
  `fixtures/` and its own home folder. DT's vault folders, exports and file-chooser picks must
  stay inside it. The harness refuses anything else and labels the refusal `[Jev sandbox]`.
- **Network:** every urllib request DT makes is recorded, with header names only. In `block` mode
  the request is refused, and so are non-loopback sockets. `mock` answers the AI, NHVR and FFmpeg
  endpoints with canned responses. `allow` sends real requests, so use it only on purpose, with
  `--allow-host`.
- **Environment:** secrets (`*KEY*`, `*TOKEN*` and so on) are stripped from the app's environment.
- **Test data:** fixtures are synthetic: test patterns, tones, corrupt, empty and oddly named files,
  and catalogue JSON.
- **Limits:** this is a test harness, not a security boundary. DT runs with your account's
  permissions.

## Known limits of the harness

- **Offscreen rendering:** fonts and styles are close to Linux desktops but not identical to
  Windows or macOS, and video frames are not drawn, although playback, position and clipping work.
  Confirm pixel-level issues on a real desktop, for example with `--visible`.
- **File dialogs:** native file dialogs are replaced by a sandbox-limited chooser. Native dialog
  behaviour is out of scope.
- **Audit:** the layout and accessibility checks are heuristics, so confirm them with a
  screenshot.
- **Model memory:** long OpenRouter sessions summarise older steps. Testers keep notes with `note`,
  and the harness re-injects the notes and the findings list every turn.
- **Code coverage** is measured with coverage.py when the app interpreter has it (install
  `coverage`); without it, coverage is off unless `--coverage on` selects a slower pure-Python
  tracer. Coverage starts after DT is imported, so module-level lines are not counted: the
  dataset reports coverage per function body.
- **Model catalogue:** `auto`, `auto-vision` and `auto-budget[:N]` pick models from OpenRouter's
  live list (tool calling, a large enough context, one per provider). Presets are a fallback and
  can go stale; `jev models --pick auto:3` shows what would be chosen.
- **Windows:** paths, long file names and console encoding are handled (output is UTF-8; the
  offscreen screen config uses a relative path because drive letters break Qt's platform
  string). The integration tests have run on Linux; please report anything Windows-specific.

## Development

```bash
python -m unittest discover -s tests -v    # the integration tests start the real app offscreen
```

- **Main modules:**
  - `jev/host/` runs inside the app: `describe.py` makes snapshots, `actions.py` sends input,
    `guards.py` holds the sandbox and file chooser, `server.py` is the control server,
    `monitor.py` and `observers.py` record events, and `coverage_probe.py` measures DT code.
  - `jev/tools.py` is the shared tool layer and writes each run's `steps.jsonl`.
  - `jev/agent/` contains the OpenRouter client, agent loop, matrix runner and model picker.
  - `jev/scenarios.py` (scenarios, sweep, recording), `jev/crawler.py`, `jev/campaign.py`.
  - `jev/dataset.py`, `jev/registry.py`, `jev/dtsource.py` (static index of DT's source),
    `jev/verify.py` and `jev/triage.py` build and maintain the improvement dataset.
- **Adapting to another PySide6 app:** most of the harness is generic Qt. The DT-specific parts
  are in `host/main.py`, `host/guards.py` (`install_dt_path_guards`) and `host/seed.py`.
