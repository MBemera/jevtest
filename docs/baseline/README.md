# Baseline: Jev campaign against DT `6ead556`

This folder is a shareable export (`jev dataset export`) of the first full Jev campaign. It shows
what the dataset gives DT's developers, and it is a starting point for fixes. Regenerate it any
time with:

```bash
jev campaign --crawls 3 --crawl-steps 250 --random-seed 11
jev dataset export --to docs/baseline
```

## What ran

| Stage | Result | Time | Detail |
|---|---|---|---|
| environment | ok | 0.0s | DT 6ead5563ebbf, FFmpeg yes, OpenRouter key no |
| dt-tests | ok | 102.7s | core: 256 tests, OK (skipped=1); desktop: 71 tests, OK |
| sweep | ok | 264.8s | 13/16 scenarios passed |
| verify | ok | 90.8s | 10 reproduced |
| crawl | ok | 317.2s | sample r11: 137 controls, 0 findings; none r12: 123 controls, 1 findings; empty r13: 139 controls, 0 findings |
| minimise | ok | 1.5s | nothing new to minimise |
| gaps | skipped | 0s | only needed for AI gap missions |
| ai-testers | skipped | 0s | no --budget given (AI testers cost money) |
| dataset | ok | 1.3s | 10 open issues, 65 backlog items, DT code exercised 76.4% |

The three sweep journeys that did not pass failed only at their checks for known issues:
09-ai-report (JEV-0003), 12-module-builder (JEV-0008) and 13-maintenance (JEV-0006).

No OpenRouter testers took part (no budget or key), so the campaign cost nothing. The same
campaign with `--budget` adds AI testers on core missions and on missions written from the
coverage gaps below.

## What it found

All 10 issues are confirmed on DT `6ead556`. Each one has a replayable regression
scenario that `jev verify` ran and saw fail, and a brief in [handoff/issues/](handoff/issues/).

| ID | Severity | Issue | Where to look |
|---|---|---|---|
| [JEV-0001](handoff/issues/JEV-0001.md) | high | Mouse wheel over the Mark dropdown can set CF and permanently stop the session with no confirmation | `dt/ui.py:748`, `dt/drafts.py:47` |
| [JEV-0002](handoff/issues/JEV-0002.md) | high | Typing a truck make key by key saves a corrupted value (KENWORTH becomes KENWORTHWORTH) | `dt/ui.py:640`, `dt/ui.py:653` |
| [JEV-0003](handoff/issues/JEV-0003.md) | high | Cancel report request does nothing while an AI draft is being requested | `dt/ui.py:960`, `dt/ui.py:567` |
| [JEV-0009](handoff/issues/JEV-0009.md) | medium | The unlock dialog shows raw system errors ([Errno 2] No such file or directory, [Errno 36] File name too long) | `dt/ui.py:198`, `dt/ui.py:206` |
| [JEV-0004](handoff/issues/JEV-0004.md) | medium | Cancel registration check does nothing while the NHVR request is running | `dt/ui.py:672`, `dt/ui.py:1845` |
| [JEV-0005](handoff/issues/JEV-0005.md) | medium | After Check video file finishes, the file selection is cleared, so the next evidence action fails | `dt/ui.py:1759`, `dt/ui.py:1222` |
| [JEV-0006](handoff/issues/JEV-0006.md) | medium | Backing up into the vault folder fails with a generic message that hides the reason | `dt/ui.py:143`, `dt/storage.py:569` |
| [JEV-0007](handoff/issues/JEV-0007.md) | medium | Help guide says video playback is not built in, but Evidence has in-app playback and clipping | `dt/help_guide.py:51`, `dt/help_guide.py:93` |
| [JEV-0010](handoff/issues/JEV-0010.md) | medium | Checking a damaged video shows raw FFprobe output (moov atom not found, memory addresses, internal paths) | `dt/media.py:237`, `dt/media.py:166` |
| [JEV-0008](handoff/issues/JEV-0008.md) | low | Module builder clears the module selection after excluding it, so Restore needs a reselect | `dt/assessment_ui.py:235`, `dt/assessment_ui.py:374` |

Two of these are new in this campaign. The first-run crawler reached the unlock dialog's raw
`[Errno 2]` / `[Errno 36]` messages (JEV-0009). The sweep's damaged-video import surfaced the
raw FFprobe output (JEV-0010). Both became regression scenarios, so Jev can tell when a fix
lands.

## Beyond bugs

- **Code reached:** 76.4% of DT's function statements (455/521 functions) across 27 runs.
  [improvements.md](improvements.md) and `code_files.csv` list the functions no run reached, and
  those that people use but DT's own tests do not cover.
- **Accessibility:** 10 controls have no accessible name. These include the
  assessment list, the evidence and findings lists, the playback slider and several module
  builder fields.
- **Copy:** DT's text names the same idea with different words: vault/records,
  assessment/session, evidence/recording/video, sign/signature (`copy_terms.csv`).
- **Screens never shown:** 7 labels DT defines never appeared in any run
  (`ui_unseen.csv`). An example is the FFmpeg install flow, which needs FFmpeg to be missing.

## Using it

Start with [handoff/README.md](handoff/README.md). Each brief contains:

- the repro steps and the evidence
- the DT code to look at, with excerpts
- a suggested DT regression test
- a task statement for a coding agent working in the DT repository

After a fix, run `JEV_DT_PATH=<DT checkout> jev verify --issue JEV-XXXX` from this repository. It
marks the issue fixed against that DT commit.
