# The Jev improvement dataset

`jev dataset build` reads every run under the runs folder and writes one dataset that DT's
developers can act on. `jev campaign` rebuilds it at the end of every campaign. This page
describes what is in it, how issues are tracked, and how to use it to improve DT.

## Where it comes from

| Source | Folder | What it adds |
| --- | --- | --- |
| AI testers (`jev run`, `jev matrix`, campaign ai-testers) | `runs/<run>/`, `runs/matrix-*/<run>/` | findings with steps, evidence and confidence; exploration of UX |
| Claude Code / Codex through MCP or the CLI | `runs/mcp-*/`, `runs/cli-*/` | the same, from an interactive agent |
| Scripted sweep and scenarios | `runs/sweep-*/<scenario>/`, `runs/scenario-*/` | deterministic journeys through every feature; failed expectations |
| Regression checks (`jev verify`) | `runs/verify-*/<issue>/` | whether each known issue still happens on a DT commit |
| Crawler | `runs/crawl-*/` | broad coverage with edge-case input; crashes and exceptions with replays |
| DT's own tests (campaign) | `runs/campaign-*/dt-tests/` | failing DT tests; which DT code the tests cover |

Every run records `steps.jsonl` (one line per tool call, with the control acted on and the
controls visible afterwards), `findings.jsonl`, evidence, and `app/coverage.json` (the DT lines
that ran). Every run also records the DT commit it ran against.

## Tables

All tables are in `jev-dataset.sqlite` and also as CSV (steps as JSONL).

| Table | One row per | Key columns |
| --- | --- | --- |
| `runs` | run | `kind` (agent, scenario, crawl, cli, dt-tests), `group` (matrix, sweep, regression, verify), `model`, `mission`, `persona`, `dt_commit`, `dt_dirty`, `steps`, `actions`, `errors`, `findings`, `cost`, `outcome`, `passed` |
| `steps` | tool call | `run`, `step`, `tool`, `args`, `ok`, `latency_ms`, `screen_before`, `screen_after`, `target` (window, tab, role, name, key), `events` (dialogs with messages, status text, exceptions, network, stalls), `controls` (keys of the visible controls), `findings` |
| `findings` | raw finding | `run`, `id`, `source`, `title`, `severity`, `category`, `confidence`, `signature`, `steps`, `expected`, `actual`, `evidence`, `issue_id` |
| `issues` | distinct issue | `id`, `status`, `classification`, `severity`, `category`, `score`, `rank`, `occurrences`, `runs`, `reporters`, `steps`, `code` (file, line, function, why), `suspected`, `scenario`, `verify_kind`, `status_history`, `verifications`, `dt_commits`, `known_limitation` |
| `ui_controls` | control seen on screen | `key` (window, tab, role, name), `seen_steps`, `runs_seen`, `used`, `used_ok`, `used_failed`, `used_by` (per run kind), `unlabelled` |
| `ui_unseen` | label defined in DT's code but never on screen | `text`, `kind` (button, tab, title, field...), `file`, `line`, `function` |
| `code_functions` | DT function | `file`, `function`, `statements`, `hit`, `percent`, `runs`, `by_crawler`, `by_scenarios`, `by_agents`, `dt_tests_hit`, `missed_lines` |
| `code_files` | DT module | `functions`, `functions_run`, `statements`, `hit`, `percent`, `dt_tests_hit` |
| `copy_texts` | user-facing text | `text`, `kind`, `where`, `origin` (source or screen), `seen` |
| `copy_problems` | wording problem | `check` (technical error text, unfilled placeholder, technical term, too long, inconsistent capitalisation), `severity`, `detail` |
| `copy_terms` | concept named several ways | `concept`, `terms` with counts, `examples` |
| `inputs` | value typed into a field | `field`, `input_class` (empty, whitespace, very long, markup/script, sql-like, path-like, format tokens, invalid date, number, non-ASCII, multi-line, ordinary), `value`, `submit`, `reaction` (dialogs in the next steps) |
| `performance` | action on a control | `count`, `median_ms`, `p90_ms`, `max_ms`, `stalls`, `worst_stall_s` |
| `improvements` | backlog item | `id`, `kind`, `priority`, `rank`, `severity`, `title`, `detail`, `where`, `action` |

`history.jsonl` (not a table) gets one line per build whose numbers changed: DT commit, open
issues by severity and status, code and UI coverage, unlabelled controls and copy problems.
`improvements.md` shows the last ten as a trend, so the effect of DT fixes is visible over time.

Code coverage is measured on one DT commit, the current checkout when runs exist for it. Runs on
other commits still count for issues and UI coverage. `code_functions.dt_tests_hit` is filled when
a campaign ran DT's own tests. Code that people reach through the UI but no DT test covers is a
good place for new DT tests.

## Issues and their lifecycle

Findings are merged into issues in `registry.json`:

- A finding that names its issue (regression scenarios and sweep checks do) joins it directly.
- Findings with the same signature (harness exceptions, crashes, freezes, scenario steps, DT
  tests) join the same issue. Harness findings never merge on similar wording alone.
- Tester reports join an issue when their titles are similar and the category matches, or when
  they concern the same control and are fairly similar.
- Anything else becomes a new issue. Each finding's assignment is remembered, so rebuilding never
  moves or duplicates it.

| Status | Meaning | Set by |
| --- | --- | --- |
| `open` | happens on the latest DT checked | first sighting; `jev verify` when reproduced |
| `fixed` | the replay passes | `jev verify`; DT tests passing again; `jev issues set` |
| `regressed` | was fixed, then seen or reproduced again | `jev verify`; any later run that reports it |
| `wontfix`, `by-design`, `known-limitation`, `harness-artefact`, `duplicate` | triage decisions | `jev issues set`, `jev triage` (when confident), MCP `set_issue` |

`classification` records what the issue is (confirmed bug, UX issue, by design, known limitation,
harness artefact, or unconfirmed). Harness exceptions, crashes, freezes, failing DT tests and
built-in known issues start confirmed. Tester reports and failed scripted steps start unconfirmed
until someone triages them.

`verify_kind` says how `jev verify` decides:

- `expectations`: the issue's regression scenario checks the correct behaviour. It passes once
  the issue is fixed.
- `signature`: the replay must no longer produce the finding's signature, such as the same
  exception at the same place.
- `manual`: a tester's report. `jev verify --include-manual` replays the steps to the reported
  point, and a person judges the result.

When `jev dataset build` finds an issue without a scenario, it gives the issue a replay. It uses
the crawler's repro, the scripted scenario, or a recording of the run up to the finding. Replays
are in `dataset/scenarios/`. For issues the harness recognises by signature, `jev minimise ID`
(run automatically by campaigns for new issues) cuts the replay down to the steps that still
produce the signature. The brief then shows these minimal steps.

## Priority

Issues: severity points (critical 100, high 60, medium 30, low 10, info 3), multiplied by:

- the category weight (data loss, crash and security x1.5; exception and freeze x1.25; functional x1.1)
- confidence (confirmed 1, likely 0.8, possible 0.5)
- reach: 1 + log2(1 + runs that hit it)
- reporters: +25% per extra independent reporter
- status: x1.3 when regressed
- x0.3 when it matches a limitation DT documents as not implemented

Other backlog items use fixed scores so that confirmed bugs come first:

| Item | Score |
| --- | --- |
| technical error text shown to users | 30 |
| freeze of 2 s or more | 25 |
| unlabelled control | 20 |
| label never shown | 12 |
| untested function | 8 to 40, by size |
| missing DT unit test | 5 to 25 |
| mixed terminology | 8 |
| long text | 6 |

## Using it in DT

1. Start from `handoff/README.md` and the top of `improvements.md`.
2. Each brief in `handoff/issues/` has repro steps, expected and actual behaviour, evidence, the
   code Jev located (with excerpts), a suggested DT regression test where known, a definition of
   done, and a task statement to give a coding agent working in the DT repository.
   `handoff/issues.json` has the same data.
3. Fix it on a DT branch and add a DT regression test. Then, from this repository, run
   `JEV_DT_PATH=/path/to/that/checkout jev verify --issue JEV-XXXX`. The registry records the
   result against that DT commit.
4. Coverage gaps and labels never shown point at screens no tester has reached. Campaigns turn
   them into missions for AI testers (`runs/campaign-*/missions/gap-*.md`). DT developers can use
   them to check that the screens are reachable.
5. `inputs.csv` shows which unusual values each field accepted and what DT said. It is a quick way
   to review validation rules.

## Sharing

The dataset folder is plain files. `registry.json` is the only part with state that matters
between builds: commit or copy it to keep issue IDs and history consistent across machines.
Everything else is rebuilt from the runs. Runs contain only synthetic data, but evidence
screenshots show the app, so review them before sharing outside your team.
