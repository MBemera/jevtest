# DT improvement backlog (from Jev runs)

Built 2026-09-29T06:15:41 by Jev 0.1.0 from 30 runs (3 crawl, 1 dt-tests, 26 scenario), 1363 steps and 18 findings.
DT checkout: `6ead5563ebbf`; coverage measured on `6ead5563ebbf`.

## At a glance

- **Open issues:** 10 (3 high, 6 medium, 1 low)
- **Issue status:** 10 open
- **DT code run by testers:** 76.4% of statements (455/521 functions) over 27 runs
- **UI:** 304 controls seen, 238 used, 10 unlabelled; 7 labels defined in DT never appeared on screen
- **Copy:** 0 wording problems, 4 mixed-term groups

## Ranked backlog

| # | ID | Kind | Severity | Priority | What | Where |
|---|---|---|---|---|---|---|
| 1 | JEV-0001 | issue | high | 180.0 | Mouse wheel over the Mark dropdown can set CF and permanently stop the session with no confirmation | dt/ui.py:748 (MainWindow.mark_box), dt/drafts.py:47 (DraftBuffer.mark) |
| 2 | JEV-0002 | issue | high | 132.0 | Typing a truck make key by key saves a corrupted value (KENWORTH becomes KENWORTHWORTH) | dt/ui.py:640 (MainWindow.searchable_combo), dt/ui.py:653 (MainWindow.vehicle_rows) |
| 3 | JEV-0003 | issue | high | 132.0 | Cancel report request does nothing while an AI draft is being requested | dt/ui.py:960 (MainWindow.finalise_tab), dt/ui.py:567 (MainWindow.button) |
| 4 | JEV-0009 | issue | medium | 75.0 | The unlock dialog shows raw system errors ([Errno 2] No such file or directory, [Errno 36] File name too long) | dt/ui.py:198 (UnlockDialog.unlock), dt/ui.py:206 (UnlockDialog.unlock) |
| 5 | JEV-0004 | issue | medium | 66.0 | Cancel registration check does nothing while the NHVR request is running | dt/ui.py:672 (MainWindow.registration_rows), dt/ui.py:1845 (MainWindow.busy) |
| 6 | JEV-0005 | issue | medium | 60.0 | After Check video file finishes, the file selection is cleared, so the next evidence action fails | dt/ui.py:1759 (MainWindow.analysis_complete), dt/ui.py:1222 (MainWindow.populate_session) |
| 7 | JEV-0006 | issue | medium | 60.0 | Backing up into the vault folder fails with a generic message that hides the reason | dt/ui.py:143 (MaintenanceWorker.run), dt/storage.py:569 (Vault.backup) |
| 8 | JEV-0007 | issue | medium | 60.0 | Help guide says video playback is not built in, but Evidence has in-app playback and clipping | dt/help_guide.py:51 (), dt/help_guide.py:93 () |
| 9 | JEV-0010 | issue | medium | 60.0 | Checking a damaged video shows raw FFprobe output (moov atom not found, memory addresses, internal paths) | dt/media.py:237 (probe_media), dt/media.py:166 (error_tail) |
| 10 | JEV-0008 | issue | low | 20.0 | Module builder clears the module selection after excluding it, so Restore needs a reselect | dt/assessment_ui.py:235 (AssessmentBuilder.refresh), dt/assessment_ui.py:374 (AssessmentBuilder.selected_scope) |
| 11 | A11Y-8300837e | accessibility | medium | 20.0 | Unlabelled textarea in Approve report request |  |
| 12 | A11Y-eb93bb5f | accessibility | medium | 20.0 | Unlabelled combobox in Build assessment scope / Modules |  |
| 13 | A11Y-cb63b1e7 | accessibility | medium | 20.0 | Unlabelled list in Build assessment scope / Modules |  |
| 14 | A11Y-7a8bdd4b | accessibility | medium | 20.0 | Unlabelled textbox in Build assessment scope / Modules |  |
| 15 | A11Y-6e74fb4d | accessibility | medium | 20.0 | Unlabelled textarea in Build assessment scope / Review and catalogue |  |
| 16 | A11Y-0e6667d8 | accessibility | medium | 20.0 | Unlabelled list in DT \| Driver training |  |
| 17 | A11Y-f880da87 | accessibility | medium | 20.0 | Unlabelled slider in DT \| Driver training |  |
| 18 | A11Y-7202d892 | accessibility | medium | 20.0 | Unlabelled list in DT \| Driver training / 3 Evidence |  |
| 19 | A11Y-9eb04b4a | accessibility | medium | 20.0 | Unlabelled list in DT \| Driver training / 5 Findings review |  |
| 20 | A11Y-3d0e29f0 | accessibility | medium | 20.0 | Unlabelled textarea in Review AI report draft |  |
| 21 | GAP-ea6d740a | untested code | low | 12.7 | No run has executed MainWindow.install_ffmpeg (14 statements) and DT's own tests do not either | dt/ui.py:1640 |
| 22 | UNSEEN-deda7a22 | never on screen | low | 12.0 | 1 label(s) from MainWindow.evidence_tab never appeared in any run | dt/ui.py:896 |
| 23 | UNSEEN-0568a849 | never on screen | low | 12.0 | 1 label(s) from MainWindow.create_session never appeared in any run | dt/ui.py:1095 |
| 24 | UNSEEN-5ef60363 | never on screen | low | 12.0 | 1 label(s) from MainWindow.create_from_directory never appeared in any run | dt/ui.py:1168 |
| 25 | UNSEEN-ea6d740a | never on screen | low | 12.0 | 1 label(s) from MainWindow.install_ffmpeg never appeared in any run | dt/ui.py:1643 |
| 26 | UNSEEN-223315eb | never on screen | low | 12.0 | 1 label(s) from MainWindow.unlock_records never appeared in any run | dt/ui.py:2011 |
| 27 | UNSEEN-197e9c33 | never on screen | low | 12.0 | 2 label(s) from MainWindow.closeEvent never appeared in any run | dt/ui.py:2057 |
| 28 | GAP-bb339f69 | untested code | low | 11.3 | No run has executed FfmpegInstallWorker.run (10 statements) and DT's own tests do not either | dt/ffmpeg_ui.py:13 |
| 29 | GAP-3faaab58 | untested code | low | 11.3 | No run has executed MainWindow.validate_current_module (10 statements) and DT's own tests do not either | dt/ui.py:1310 |
| 30 | GAP-efb73031 | untested code | low | 11.0 | No run has executed AssessmentBuilder.validate_selected (9 statements) and DT's own tests do not either | dt/assessment_ui.py:416 |
| 31 | GAP-91203cf2 | untested code | low | 10.7 | No run has executed AssessmentBuilder.add_custom (8 statements) and DT's own tests do not either | dt/assessment_ui.py:520 |
| 32 | GAP-44c6ffb8 | untested code | low | 10.3 | No run has executed MainWindow.restore_current_module_criterion (7 statements) and DT's own tests do not either | dt/ui.py:1333 |
| 33 | TEST-e9bcc62c | missing unit test | low | 9.8 | MainWindow.draft_report runs when people use DT but no DT test covers it | dt/ui.py:1406 |
| 34 | TEST-031e67df | missing unit test | low | 9.4 | get_json runs when people use DT but no DT test covers it | dt/registration.py:77 |
| 35 | TEST-e9bd059d | missing unit test | low | 9.4 | ReportSetupDialog.__init__ runs when people use DT but no DT test covers it | dt/report_ui.py:23 |
| 36 | TEST-b2fdf15f | missing unit test | low | 9.2 | AssessmentBuilder.edit_catalogue_criterion runs when people use DT but no DT test covers it | dt/assessment_ui.py:451 |
| 37 | TEST-87d0f1b7 | missing unit test | low | 8.8 | ReportPromptDialog.__init__ runs when people use DT but no DT test covers it | dt/report_ui.py:66 |
| 38 | TEST-24bcce0f | missing unit test | low | 8.6 | AssessmentBuilder.edit_unit runs when people use DT but no DT test covers it | dt/assessment_ui.py:274 |
| 39 | TEST-d94f825e | missing unit test | low | 8.2 | ReportReviewDialog.__init__ runs when people use DT but no DT test covers it | dt/report_ui.py:90 |
| 40 | TEST-ae834942 | missing unit test | low | 8.2 | MaintenanceWorker.run runs when people use DT but no DT test covers it | dt/ui.py:143 |
| 41 | TEST-a747ec8e | missing unit test | low | 8.2 | MainWindow.report_draft_ready runs when people use DT but no DT test covers it | dt/ui.py:1432 |
| 42 | TERMS-a1db32ba | copy | low | 8.0 | Mixed words for the encrypted store: 'vault' x11, 'records' x15 |  |
| 43 | TERMS-0eeffe59 | copy | low | 8.0 | Mixed words for one driver's assessment: 'assessment' x29, 'session' x3 |  |
| 44 | TERMS-9b76be63 | copy | low | 8.0 | Mixed words for evidence files: 'evidence' x24, 'recording' x4, 'video' x10 |  |
| 45 | TERMS-5a196401 | copy | low | 8.0 | Mixed words for signing: 'sign' x4, 'signature' x3 |  |
| 46 | TEST-001d6141 | missing unit test | low | 7.8 | AssessmentBuilder.edit_connection runs when people use DT but no DT test covers it | dt/assessment_ui.py:304 |
| 47 | TEST-fddaba56 | missing unit test | low | 7.8 | AssessmentBuilder.finish runs when people use DT but no DT test covers it | dt/assessment_ui.py:427 |
| 48 | TEST-f1a13250 | missing unit test | low | 7.8 | ImportWorker.run runs when people use DT but no DT test covers it | dt/ui.py:57 |
| 49 | TEST-d551104b | missing unit test | low | 7.8 | AnalysisWorker.run runs when people use DT but no DT test covers it | dt/ui.py:92 |
| 50 | TEST-20e28652 | missing unit test | low | 7.8 | MainWindow.mark_evidence_reviewed runs when people use DT but no DT test covers it | dt/ui.py:1554 |
| 51 | TEST-b13d3dfa | missing unit test | low | 7.4 | AssessmentBuilder.edit_parameters runs when people use DT but no DT test covers it | dt/assessment_ui.py:392 |
| 52 | TEST-f71ac4a5 | missing unit test | low | 7.4 | PlaybackWorker.run runs when people use DT but no DT test covers it | dt/playback_ui.py:30 |
| 53 | TEST-b28dbe94 | missing unit test | low | 7.4 | MainWindow.use_video_moment runs when people use DT but no DT test covers it | dt/ui.py:1683 |
| 54 | TEST-cbba5b93 | missing unit test | low | 7.4 | MainWindow.export runs when people use DT but no DT test covers it | dt/ui.py:1848 |
| 55 | TEST-b043c28f | missing unit test | low | 7.2 | AssessmentBuilder.load_template runs when people use DT but no DT test covers it | dt/assessment_ui.py:476 |
| 56 | TEST-33e13cb1 | missing unit test | low | 7.2 | RegistrationApprovalDialog.__init__ runs when people use DT but no DT test covers it | dt/registration_ui.py:41 |
| 57 | TEST-6a1d190b | missing unit test | low | 7.2 | AnalysisWorker.perform runs when people use DT but no DT test covers it | dt/ui.py:109 |
| 58 | TEST-56d62a6b | missing unit test | low | 7.0 | AssessmentBuilder.edit_jurisdiction runs when people use DT but no DT test covers it | dt/assessment_ui.py:324 |
| 59 | TEST-03540e50 | missing unit test | low | 7.0 | AssessmentBuilder.import_pack runs when people use DT but no DT test covers it | dt/assessment_ui.py:495 |
| 60 | TEST-b361b004 | missing unit test | low | 7.0 | MainWindow.watch_video runs when people use DT but no DT test covers it | dt/ui.py:1663 |

5 more in improvements.csv.

## Open issues

### JEV-0001 (open, high data-loss): Mouse wheel over the Mark dropdown can set CF and permanently stop the session with no confirmation

Priority 180.0; seen 1 time(s) in 1 run(s) by scenario; classification: confirmed bug.

- Expected: Wheel scrolling over the Mark dropdown does not change the mark (or CF asks for confirmation), and returning the mark leaves the outcome unchanged.
- Actual: Four wheel notches move C -> D -> NYC -> NA -> CF with autosave; the record becomes STOPPED / Not yet competent and stays so after the mark is changed back.
- Code: `dt/ui.py:748` MainWindow.mark_box (named in the issue: dt/ui.py: MainWindow.mark_box QComboBox accepts wheel events without focus)
- Code: `dt/drafts.py:47` DraftBuffer.mark (named in the issue: dt/drafts.py: DraftBuffer.mark keeps state 'stopped' once any CF was recorded)
- Suspected: dt/ui.py: MainWindow.mark_box QComboBox accepts wheel events without focus
- Suspected: dt/drafts.py: DraftBuffer.mark keeps state 'stopped' once any CF was recorded
- Brief: handoff/issues/JEV-0001.md

### JEV-0002 (open, high functional): Typing a truck make key by key saves a corrupted value (KENWORTH becomes KENWORTHWORTH)

Priority 132.0; seen 1 time(s) in 1 run(s) by scenario; classification: confirmed bug.

- Expected: After typing KENWORTH and pressing Tab, Truck make is KENWORTH and no 'not in the register' note appears.
- Actual: The field holds KENWORTHWORTH ('Ken' gives 'KenT KENWORTH'), and DT records that value.
- Code: `dt/ui.py:640` MainWindow.searchable_combo (named in the issue: dt/ui.py: MainWindow.searchable_combo sets Qt.MatchContains on the editable combo's defaul)
- Code: `dt/ui.py:653` MainWindow.vehicle_rows (string text 'Truck make')
- Code: `dt/reports.py:66`  (string text 'Truck make')
- Suspected: dt/ui.py: MainWindow.searchable_combo sets Qt.MatchContains on the editable combo's default InlineCompletion completer
- Brief: handoff/issues/JEV-0002.md

### JEV-0003 (open, high functional): Cancel report request does nothing while an AI draft is being requested

Priority 132.0; seen 2 time(s) in 2 run(s) by scenario; classification: confirmed bug.

- Expected: Cancel report request stops waiting at once and the status bar says the request was cancelled (README promise).
- Actual: The click is ignored until the provider answers.
- Code: `dt/ui.py:960` MainWindow.finalise_tab (named in the issue: dt/ui.py: finalise_tab wires 'Cancel report request' through MainWindow.button -> run_acti)
- Code: `dt/ui.py:567` MainWindow.button (named in the issue: dt/ui.py: finalise_tab wires 'Cancel report request' through MainWindow.button -> run_acti)
- Code: `dt/ui.py:1429` MainWindow.draft_report (status text 'Requesting an AI draft. Review it before applying; Cancel re')
- Suspected: dt/ui.py: finalise_tab wires 'Cancel report request' through MainWindow.button -> run_action, which returns while busy()
- Brief: handoff/issues/JEV-0003.md

### JEV-0009 (open, medium copy): The unlock dialog shows raw system errors ([Errno 2] No such file or directory, [Errno 36] File name too long)

Priority 75.0; seen 7 time(s) in 2 run(s) by crawler, scenario; classification: ux issue.

- Expected: A plain message such as 'No vault in this folder. Tick Create a new vault to make one here.', or 'This folder name is too long'.
- Actual: 'Could not open records' shows Python's OSError text with the full path, e.g. [Errno 2] No such file or directory: '<folder>/vault.lock'.
- Code: `dt/ui.py:198` UnlockDialog.unlock (named in the issue: dt/ui.py: UnlockDialog.unlock shows str(error) for every exception, including OSError from)
- Code: `dt/ui.py:206` UnlockDialog.unlock (title text 'Could not open records')
- Code: `dt/ui.py:181` UnlockDialog.__init__ (placeholder text 'Vault passphrase')
- Suspected: dt/ui.py: UnlockDialog.unlock shows str(error) for every exception, including OSError from Vault()
- Brief: handoff/issues/JEV-0009.md

### JEV-0004 (open, medium functional): Cancel registration check does nothing while the NHVR request is running

Priority 66.0; seen 1 time(s) in 1 run(s) by scenario; classification: confirmed bug.

- Expected: Cancel registration check stops waiting at once and says so.
- Actual: The click is ignored until NHVR answers.
- Code: `dt/ui.py:672` MainWindow.registration_rows (named in the issue: dt/ui.py: registration_rows connects every button, including Cancel registration check, th)
- Code: `dt/ui.py:1845` MainWindow.busy (named in the issue: dt/ui.py: registration_rows connects every button, including Cancel registration check, th)
- Code: `dt/registration.py:77` get_json (named in the issue: dt/registration.py: get_json blocks in opener.open for up to 15 s, so even a wired button )
- Suspected: dt/ui.py: registration_rows connects every button, including Cancel registration check, through run_action, which returns while busy()
- Suspected: dt/registration.py: get_json blocks in opener.open for up to 15 s, so even a wired button would wait
- Brief: handoff/issues/JEV-0004.md

### JEV-0005 (open, medium ux): After Check video file finishes, the file selection is cleared, so the next evidence action fails

Priority 60.0; seen 1 time(s) in 1 run(s) by scenario; classification: confirmed bug.

- Expected: After the media check the same file stays selected and Watch video and mark assessment opens it.
- Actual: The evidence list is rebuilt with nothing selected and the next button warns 'Select an imported file first'.
- Code: `dt/ui.py:1759` MainWindow.analysis_complete (named in the issue: dt/ui.py: MainWindow.analysis_complete -> refresh_sessions -> populate_session clears self)
- Code: `dt/ui.py:1222` MainWindow.populate_session (named in the issue: dt/ui.py: MainWindow.analysis_complete -> refresh_sessions -> populate_session clears self)
- Code: `dt/ui.py:1599` MainWindow.selected_asset (error text 'Select an imported file first')
- Suspected: dt/ui.py: MainWindow.analysis_complete -> refresh_sessions -> populate_session clears self.assets
- Brief: handoff/issues/JEV-0005.md

### JEV-0006 (open, medium ux): Backing up into the vault folder fails with a generic message that hides the reason

Priority 60.0; seen 2 time(s) in 2 run(s) by scenario; classification: confirmed bug.

- Expected: The status says 'Choose a backup location outside the active vault'.
- Actual: The status says 'Operation failed. Check destination space, file access and evidence integrity.'
- Code: `dt/ui.py:143` MaintenanceWorker.run (named in the issue: dt/ui.py: MaintenanceWorker.run replaces every exception with one generic message)
- Code: `dt/storage.py:569` Vault.backup (error text 'Choose a backup location outside the active vault')
- Code: `dt/ui.py:157` MaintenanceWorker.run (string text 'Operation failed. Check destination space, file access and e')
- Suspected: dt/ui.py: MaintenanceWorker.run replaces every exception with one generic message
- Brief: handoff/issues/JEV-0006.md

### JEV-0007 (open, medium copy): Help guide says video playback is not built in, but Evidence has in-app playback and clipping

Priority 60.0; seen 1 time(s) in 1 run(s) by scenario; classification: confirmed bug.

- Expected: The 'Evidence and review copies' topic describes Watch video and mark assessment, clipping and Install FFmpeg for video features.
- Actual: It says 'Watch the recording in your video player ... Playback is not built into this version.' and to ask support to configure FFmpeg.
- Code: `dt/help_guide.py:51`  (string text 'Evidence and review copies')
- Code: `dt/help_guide.py:93`  (string text 'Evidence and review copies')
- Code: `dt/help_guide.py:52`  (string text 'Playback is not built into this version')
- Suspected: dt/help_guide.py: TOPICS['Evidence and review copies']
- Brief: handoff/issues/JEV-0007.md

### JEV-0010 (open, medium copy): Checking a damaged video shows raw FFprobe output (moov atom not found, memory addresses, internal paths)

Priority 60.0; seen 3 time(s) in 2 run(s) by scenario; classification: ux issue.

- Expected: A plain message such as 'This file is not a playable video; it may be incomplete or damaged. Import the original recording again.', with the tool output kept for diagnostics.
- Actual: The status bar shows 'FFprobe could not read this file: [mov,mp4,... @ 0x55e5...] moov atom not found <vault>/work/<id>.mp4: Invalid data found when processing input'.
- Code: `dt/media.py:237` probe_media (named in the issue: dt/media.py: probe_media raises MediaToolError('FFprobe could not read this file: ' + erro)
- Code: `dt/media.py:166` error_tail (named in the issue: dt/media.py: probe_media raises MediaToolError('FFprobe could not read this file: ' + erro)
- Code: `dt/media.py:243` probe_media (string text 'FFprobe could not read this file: [mov,mp4,... @ 0x55e5...] ')
- Suspected: dt/media.py: probe_media raises MediaToolError('FFprobe could not read this file: ' + error_tail(stderr)), and the UI shows that text as is
- Brief: handoff/issues/JEV-0010.md

### JEV-0008 (open, low ux): Module builder clears the module selection after excluding it, so Restore needs a reselect

Priority 20.0; seen 2 time(s) in 2 run(s) by scenario; classification: confirmed bug.

- Expected: The excluded module stays selected, so Restore selected module works at once.
- Actual: The selection is cleared; Restore warns 'Select an included module in the Modules tab'.
- Code: `dt/assessment_ui.py:235` AssessmentBuilder.refresh (named in the issue: dt/assessment_ui.py: AssessmentBuilder.refresh rebuilds lists without restoring the curren)
- Code: `dt/assessment_ui.py:374` AssessmentBuilder.selected_scope (error text 'Select an included module in the Modules tab')
- Code: `dt/assessment_ui.py:184` AssessmentBuilder.build_modules_tab (button text 'Restore selected module')
- Suspected: dt/assessment_ui.py: AssessmentBuilder.refresh rebuilds lists without restoring the current row
- Brief: handoff/issues/JEV-0008.md

## Code coverage by module

| Module | Functions run | Statements run | % | DT tests |
|---|---|---|---|---|
| dt/__main__.py | 0/2 | 0/17 | 0.0 | 0 |
| dt/assessment_reports.py | 0/4 | 0/24 | 0.0 | 24 |
| dt/ffmpeg_ui.py | 0/2 | 0/11 | 0.0 | 0 |
| dt/self_check.py | 0/2 | 0/22 | 0.0 | 0 |
| dt/ffmpeg_setup.py | 4/18 | 14/88 | 15.9 | 77 |
| dt/publication.py | 1/2 | 5/16 | 31.2 | 7 |
| dt/modular_assessment.py | 8/15 | 49/149 | 32.9 | 128 |
| dt/directory_validation.py | 6/6 | 27/61 | 44.3 | 57 |
| dt/boundaries.py | 1/4 | 8/17 | 47.1 | 13 |
| dt/ai.py | 12/18 | 56/104 | 53.8 | 102 |
| dt/assessment_library.py | 3/4 | 24/40 | 60.0 | 36 |
| dt/locking.py | 4/4 | 23/37 | 62.2 | 26 |
| dt/application.py | 18/23 | 147/223 | 65.9 | 202 |
| dt/reports.py | 8/9 | 83/123 | 67.5 | 108 |
| dt/playback.py | 1/1 | 15/21 | 71.4 | 18 |
| dt/processes.py | 6/6 | 40/56 | 71.4 | 49 |
| dt/assessment_scope.py | 24/25 | 168/232 | 72.4 | 196 |
| dt/media.py | 33/34 | 171/232 | 73.7 | 194 |
| dt/report_providers.py | 9/10 | 73/98 | 74.5 | 91 |
| dt/directory.py | 3/3 | 13/17 | 76.5 | 14 |
| dt/storage.py | 42/44 | 338/435 | 77.7 | 400 |
| dt/catalogue.py | 13/14 | 85/108 | 78.7 | 92 |
| dt/signatures.py | 1/1 | 15/19 | 78.9 | 17 |
| dt/assessment_ui.py | 38/42 | 329/416 | 79.1 | 218 |
| dt/registration.py | 7/8 | 55/68 | 80.9 | 44 |
| dt/drafts.py | 8/8 | 48/57 | 84.2 | 54 |
| dt/ui.py | 144/150 | 1376/1557 | 88.4 | 1193 |
| dt/domain.py | 5/5 | 40/45 | 88.9 | 43 |
| dt/vehicles.py | 7/7 | 25/28 | 89.3 | 25 |
| dt/workflow.py | 2/2 | 28/31 | 90.3 | 28 |
| dt/playback_ui.py | 16/17 | 118/129 | 91.5 | 102 |
| dt/registration_ui.py | 7/7 | 59/61 | 96.7 | 40 |
| dt/report_ui.py | 8/8 | 81/83 | 97.6 | 0 |
| dt/signature_ui.py | 9/9 | 51/52 | 98.1 | 48 |
| dt/help_guide.py | 2/2 | 22/22 | 100.0 | 22 |
| dt/presentation.py | 4/4 | 25/25 | 100.0 | 25 |
| dt/templates.py | 1/1 | 1/1 | 100.0 | 1 |

## Labels DT defines that no run has shown

- button "Install FFmpeg for video features" (dt/ui.py:896 MainWindow.evidence_tab)
- title "Could not create assessment" (dt/ui.py:1095 MainWindow.create_session)
- title "Could not create assessment" (dt/ui.py:1168 MainWindow.create_from_directory)
- title "Install FFmpeg" (dt/ui.py:1643 MainWindow.install_ffmpeg)
- title "Records stay locked" (dt/ui.py:2011 MainWindow.unlock_records)
- title "Import in progress" (dt/ui.py:2057 MainWindow.closeEvent)
- title "Unsaved edits retained" (dt/ui.py:2061 MainWindow.closeEvent)

## Mixed terminology

- **the encrypted store**: 'vault' in 11 text(s), e.g. "Back up vault"; 'records' in 15 text(s), e.g. "1. Import the recording. 2. Check the video file. 3. Record your trainer review."
- **one driver's assessment**: 'assessment' in 29 text(s), e.g. "<runs>/ca"; 'session' in 3 text(s), e.g. "Registration setup saved for this unlocked session. No request sent."
- **evidence files**: 'evidence' in 24 text(s), e.g. "3 Evidence"; 'recording' in 4 text(s), e.g. "1. Import the recording. 2. Check the video file. 3. Record your trainer review."; 'video' in 10 text(s), e.g. "1. Import the recording. 2. Check the video file. 3. Record your trainer review."
- **signing**: 'sign' in 4 text(s), e.g. "<runs>/ca"; 'signature' in 3 text(s), e.g. "Assessor: {}
Click and drag on the trackpad to draw your signature.
Save signs a"

## Slowest actions

| Action | Control | Count | Median ms | p90 ms | Worst freeze s |
|---|---|---|---|---|---|
| click | DT \| Driver training \| 4 Finalise and export \| button \| Cancel report request | 3 | 4434 | 5434 | 0 |
| click | DT \| Driver training \| 1 Prepare \| button \| Cancel registration check | 7 | 435 | 4443 | 0 |
| click | DT \| Driver training \|  \| button \| New assessment | 9 | 485 | 3759 | 0 |
| select_item | DT \| Driver training \|  \| list \|  | 28 | 3453 | 3658 | 0 |
| resize_window | DT \| Driver training \|  \| window \| DT \| Driver training | 3 | 389 | 3620 | 0 |

## How to use this

1. Take the top backlog items; each issue has a brief in `handoff/issues/` with repro steps, evidence and code.
2. Fix in DT on a branch and add a DT regression test.
3. Run `JEV_DT_PATH=<that checkout> jev verify` to replay the regression scenarios; fixed issues are marked fixed with the DT commit, and anything that breaks again is marked regressed.
4. Run `jev campaign` again and `jev dataset build` to refresh this backlog.
