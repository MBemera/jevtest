---
description: Run a full Jev campaign on DT, then triage the improvement dataset (usage: /campaign [budget in USD])
argument-hint: [budget]
---
Run a Jev campaign against the DT app and turn its results into decisions for DT's developers.

Budget for OpenRouter testers: $ARGUMENTS (empty means none: only the scripted sweep, verification,
crawlers and DT's own tests run, at no model cost).

1. Run `jev doctor`. Stop and report if DT, Qt or FFmpeg checks fail.
2. Start the campaign: `jev campaign --budget <budget>` if a budget was given, otherwise `jev campaign`.
   It takes about 15 to 25 minutes without AI testers. (From MCP: `run_campaign`, then `campaign_status`.)
3. Read `runs/campaign-*/report.md`, then `dataset/improvements.md` and `jev issues`.
4. For every issue whose classification is `unconfirmed`: reproduce it with the jev CLI or MCP tools
   using the steps in its brief (`jev issues show ID`), read the DT code the brief points at, and record
   your decision with `jev issues set ID --status ... --classification ... --note "..."`.
   Harness artefacts (offscreen rendering, the stand-in file chooser, blocked network, no audio) and
   behaviour DT documents are not DT bugs.
5. For each confirmed new bug that has no regression scenario, add one under
   `jev/data/scenarios/regressions/` with an `issue` block (next free ID below JEV-0100) that checks the
   correct behaviour, and confirm it fails today with `jev scenario run regressions/<name>`.
6. Rebuild with `jev dataset build`, then summarise for the user: DT commit, stage results, open issues
   by severity with their IDs, the three most valuable fixes, coverage gaps worth a mission, and the
   cost of any AI testers.

Never edit the DT repository during this command.
