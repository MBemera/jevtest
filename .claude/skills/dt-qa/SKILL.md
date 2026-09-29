---
name: dt-qa
description: Use when asked to QA, test, explore, find bugs, UX problems or edge cases in the DT desktop app (driver training / assessment app), to run OpenRouter AI testers against it, or to triage Jev QA findings and reports.
---
# QA the DT app with Jev

Jev runs DT offscreen in a sandbox and exposes it as text snapshots plus real mouse/keyboard
actions. Everything here is synthetic data in a disposable sandbox.

## Drive it yourself (MCP tools from `.mcp.json`, or the `jev` CLI)
- `app_start` with `seed` (`none` first run, `empty`, `sample` = 3 synthetic assessments),
  `network` (`block` default, `mock` fake AI/NHVR/FFmpeg servers), `screen`, `idle_timeout_ms`.
- `snapshot` gives refs like `w12`; act with `click`, `type_text` (submit=tab to leave a field),
  `select_option`, `select_item` (lists/trees, action=activate/check), `select_tab`, `press_key`,
  `draw` (signature pad), `scroll`, `resize_window`, `close_window`, `wait` (until=idle).
- Evidence: `screenshot` (marks=true shows refs), `audit` (layout/accessibility heuristics),
  `events`, `network_log` (exact payload DT tried to send), `read_text`, `list_items`.
- File dialogs are a stand-in "file chooser" restricted to the sandbox; fixtures to import are
  listed by `sandbox_info`.
- `report_issue` for each distinct, reproduced problem (steps from app start, expected vs actual).

## Delegate to OpenRouter testers
- `run_qa_agents` (MCP) or `jev matrix --models trio --missions ... --personas ... --max-cost 1`.
- Presets are in `jev/data/model_presets.json`; `jev models --tools` lists current model IDs.
- Follow progress with `qa_runs`; merged results land in `runs/matrix-*/summary.md`.

## Triage
Reproduce each finding, read the DT source to locate the cause, and classify it as confirmed bug,
UX issue, by design, known limitation (see DT README) or harness artefact (offscreen rendering,
stand-in file chooser, blocked network, no audio/GPU). Report confirmed items first with
minimal steps, evidence paths and suspected code locations.
