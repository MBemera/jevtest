---
description: Choose what Jev should do from a menu (campaign, sweep, crawl, verify, issues, dataset, display)
argument-hint: [what to do, optional]
---
Offer the user Jev's actions as choices, run the one they pick, and report the result. In a terminal,
the same menu opens when they run `jev` with no arguments.

What the user asked for: $ARGUMENTS

If that already says what to do (for example "sweep", "crawl from first run" or "show JEV-0003"),
skip the questions and do it. Otherwise use the AskUserQuestion tool, which shows selectable options.
You can put up to four questions in one call, so ask a follow-up question together with the choice it
depends on whenever you can.

1. Ask "What should Jev do?" (header "Jev"), with these options:
   - **Test DT**: a full campaign, the scripted sweep, a crawl, or verifying known issues.
   - **See results**: open issues, one issue's brief, or the improvement dataset.
   - **Watch or drive DT**: start DT to use it yourself, or switch between window and headless.
   - **Check setup**: `jev doctor`.
2. Ask the follow-up question for the choice:
   - **Test DT**: ask "Which test?" with these options:
     - Full campaign: DT's own tests, sweep, verify, crawlers and the dataset (15-25 min).
     - Scripted sweep: every feature (5-10 min).
     - Crawl: explores every control with awkward input.
     - Verify known issues: are they fixed on this DT checkout?

     Also ask "Where should DT run?" with the options "On screen (window)" and "Headless". Run
     `jev display` first if you need to know their current default.
   - **See results**: ask "What do you want to see?" with these options:
     - Open issues: `jev issues`.
     - An issue's brief: then offer the four highest-priority open issue IDs from `jev issues`; they
       can type any other ID with Other.
     - Dataset summary: `jev dataset show`.
     - Rebuild the dataset: `jev dataset build`.
   - **Watch or drive DT**: ask "What?" with these options:
     - Start DT on screen: `jev start --window --seed sample --network mock`.
     - Start DT headless: `jev start --headless --seed sample --network mock`.
     - Default to window: `jev display window`.
     - Default to headless: `jev display headless`.
3. Run the command from this repository with Bash, adding `--window` or `--headless` as chosen:
   - `jev campaign`, `jev sweep`, `jev crawl --seed sample --steps 250`, `jev verify`.
   - Run long commands (campaign, sweep, crawl) in the background and keep the user posted.
   - `run_campaign`, `verify_issues`, `issues` and `dataset` are MCP tools that do the same.
4. Tell the user the exact command you ran, so they can run it again or pick it from `jev`'s menu.
   Then summarise the result: what passed or failed, new or changed issues (with their `JEV-####`
   IDs), and where the report is.

Rules:
- AI testers cost money: only use `--budget` or `jev run` when the user gives an amount.
- Never pass `--allow-input` unless the user wants to use DT alongside Jev.
- Never edit the DT repository.
