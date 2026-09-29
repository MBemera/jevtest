# Jev campaign

Folder: `<runs>/campaign-baseline`  
Dataset: `<dataset>`  
Random seed: 11 (pass --random-seed to repeat the crawls)  
Duration: 778s

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

## Dataset

- Open or regressed issues: 10 of 10 ({'open': 10})
- DT code exercised by Jev: 76.4% of statements, 455/521 functions
- UI: 304 controls seen, 238 used, 10 unlabelled, 7 labels never shown
- Backlog: 65 items in `<dataset>/improvements.md`
- DT handoff: `<dataset>/handoff/README.md`

## DT's own tests

- core: 256 tests, OK (skipped=1) (log `<runs>/campaign-baseline/dt-tests/core.log`)
- desktop: 71 tests, OK (log `<runs>/campaign-baseline/dt-tests/desktop.log`)

## Known issues re-checked

| Issue | Result | Status | Why |
|---|---|---|---|
| JEV-0006 | reproduced | open | step 3 (type_text): expected a status bar message containing 'outside the active vault'; the status bar said ['Verifying encrypted records a |
| JEV-0010 | reproduced | open | step 7 (click): did not expect a message containing 'moov atom'; did not expect a message containing '@ 0x' |
| JEV-0008 | reproduced | open | step 16 (click): did not expect a message containing 'Select an included module' |
| JEV-0004 | reproduced | open | step 8 (click): expected a status bar message containing 'cancelled'; the status bar said ['Checking this plate with NHVR. Cancel check stop |
| JEV-0003 | reproduced | open | step 11 (click): expected a status bar message containing 'cancelled'; the status bar said ['Requesting an AI draft. Review it before applyi |
| JEV-0005 | reproduced | open | step 8 (click): did not expect a message containing 'Select an imported file first' |
| JEV-0007 | reproduced | open | step 3 (expect): None still contains 'Playback is not built into this version' |
| JEV-0001 | reproduced | open | step 7 (select_tab): expected the screen not to contain 'STOPPED'; expected the screen not to contain 'CRITICAL EVENT' |
| JEV-0002 | reproduced | open | step 2 (type_text): expected the screen to contain 'combobox "Truck make" = "KENWORTH"'; expected the screen not to contain 'is not in the A |
| JEV-0009 | reproduced | open | step 2 (type_text): did not expect a message containing 'Errno'; did not expect a message containing 'No such file or directory' |
