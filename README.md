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

```
 Claude Code / Codex ──MCP (stdio)──┐                  ┌──────────── app process ─────────────┐
 jev CLI (any agent's shell) ───────┼─> tools.py ──TCP─┤ control server → Qt GUI thread        │
 jev run / matrix (OpenRouter) ─────┘   findings        │ snapshot · actions · monitors · guards│
        │                               reports         │ DT: dt.ui.main() unchanged, offscreen │
        └── OpenRouter chat completions (tool calling)  └───────────────────────────────────────┘
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

This repository ships `.mcp.json`, which registers the `jev` MCP server, plus a `/qa` command
and a `dt-qa` skill. Open Claude Code in this folder and approve the server. Then ask, for
example, "QA the evidence import flow" or run `/qa evidence-media edge-case-hunter`.

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

## Development

```bash
python -m unittest discover -s tests -v    # the integration tests start the real app offscreen
```

- **Main modules:**
  - `jev/host/` runs inside the app: `describe.py` makes snapshots, `actions.py` sends input,
    `guards.py` holds the sandbox and file chooser, `server.py` is the control server, and
    `monitor.py` and `observers.py` record events.
  - `jev/tools.py` is the shared tool layer.
  - `jev/agent/` contains the OpenRouter client, agent loop and matrix runner.
- **Adapting to another PySide6 app:** most of the harness is generic Qt. The DT-specific parts
  are in `host/main.py`, `host/guards.py` (`install_dt_path_guards`) and `host/seed.py`.
