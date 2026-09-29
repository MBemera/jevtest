# Coverage, copy and speed items

Not bugs as such: places no tester reached, wording to tidy, and slow actions. Ranked.

| # | ID | Kind | What | Where | Suggested action |
|---|---|---|---|---|---|
| 11 | A11Y-8300837e | accessibility | Unlabelled textarea in Approve report request |  | setAccessibleName or a QLabel with setBuddy. |
| 12 | A11Y-eb93bb5f | accessibility | Unlabelled combobox in Build assessment scope / Modules |  | setAccessibleName or a QLabel with setBuddy. |
| 13 | A11Y-cb63b1e7 | accessibility | Unlabelled list in Build assessment scope / Modules |  | setAccessibleName or a QLabel with setBuddy. |
| 14 | A11Y-7a8bdd4b | accessibility | Unlabelled textbox in Build assessment scope / Modules |  | setAccessibleName or a QLabel with setBuddy. |
| 15 | A11Y-6e74fb4d | accessibility | Unlabelled textarea in Build assessment scope / Review and catalogue |  | setAccessibleName or a QLabel with setBuddy. |
| 16 | A11Y-0e6667d8 | accessibility | Unlabelled list in DT \| Driver training |  | setAccessibleName or a QLabel with setBuddy. |
| 17 | A11Y-f880da87 | accessibility | Unlabelled slider in DT \| Driver training |  | setAccessibleName or a QLabel with setBuddy. |
| 18 | A11Y-7202d892 | accessibility | Unlabelled list in DT \| Driver training / 3 Evidence |  | setAccessibleName or a QLabel with setBuddy. |
| 19 | A11Y-9eb04b4a | accessibility | Unlabelled list in DT \| Driver training / 5 Findings review |  | setAccessibleName or a QLabel with setBuddy. |
| 20 | A11Y-3d0e29f0 | accessibility | Unlabelled textarea in Review AI report draft |  | setAccessibleName or a QLabel with setBuddy. |
| 21 | GAP-ea6d740a | untested code | No run has executed MainWindow.install_ffmpeg (14 statements) and DT's own tests do not either | dt/ui.py:1640 | Point a Jev mission at it (campaign gap missions do this) or add a DT test. |
| 22 | UNSEEN-deda7a22 | never on screen | 1 label(s) from MainWindow.evidence_tab never appeared in any run | dt/ui.py:896 | Check how people reach this UI; aim a mission or scenario at it. |
| 23 | UNSEEN-0568a849 | never on screen | 1 label(s) from MainWindow.create_session never appeared in any run | dt/ui.py:1095 | Check how people reach this UI; aim a mission or scenario at it. |
| 24 | UNSEEN-5ef60363 | never on screen | 1 label(s) from MainWindow.create_from_directory never appeared in any run | dt/ui.py:1168 | Check how people reach this UI; aim a mission or scenario at it. |
| 25 | UNSEEN-ea6d740a | never on screen | 1 label(s) from MainWindow.install_ffmpeg never appeared in any run | dt/ui.py:1643 | Check how people reach this UI; aim a mission or scenario at it. |
| 26 | UNSEEN-223315eb | never on screen | 1 label(s) from MainWindow.unlock_records never appeared in any run | dt/ui.py:2011 | Check how people reach this UI; aim a mission or scenario at it. |
| 27 | UNSEEN-197e9c33 | never on screen | 2 label(s) from MainWindow.closeEvent never appeared in any run | dt/ui.py:2057 | Check how people reach this UI; aim a mission or scenario at it. |
| 28 | GAP-bb339f69 | untested code | No run has executed FfmpegInstallWorker.run (10 statements) and DT's own tests do not either | dt/ffmpeg_ui.py:13 | Point a Jev mission at it (campaign gap missions do this) or add a DT test. |
| 29 | GAP-3faaab58 | untested code | No run has executed MainWindow.validate_current_module (10 statements) and DT's own tests do not either | dt/ui.py:1310 | Point a Jev mission at it (campaign gap missions do this) or add a DT test. |
| 30 | GAP-efb73031 | untested code | No run has executed AssessmentBuilder.validate_selected (9 statements) and DT's own tests do not either | dt/assessment_ui.py:416 | Point a Jev mission at it (campaign gap missions do this) or add a DT test. |
| 31 | GAP-91203cf2 | untested code | No run has executed AssessmentBuilder.add_custom (8 statements) and DT's own tests do not either | dt/assessment_ui.py:520 | Point a Jev mission at it (campaign gap missions do this) or add a DT test. |
| 32 | GAP-44c6ffb8 | untested code | No run has executed MainWindow.restore_current_module_criterion (7 statements) and DT's own tests do not either | dt/ui.py:1333 | Point a Jev mission at it (campaign gap missions do this) or add a DT test. |
| 33 | TEST-e9bcc62c | missing unit test | MainWindow.draft_report runs when people use DT but no DT test covers it | dt/ui.py:1406 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 34 | TEST-031e67df | missing unit test | get_json runs when people use DT but no DT test covers it | dt/registration.py:77 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 35 | TEST-e9bd059d | missing unit test | ReportSetupDialog.__init__ runs when people use DT but no DT test covers it | dt/report_ui.py:23 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 36 | TEST-b2fdf15f | missing unit test | AssessmentBuilder.edit_catalogue_criterion runs when people use DT but no DT test covers it | dt/assessment_ui.py:451 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 37 | TEST-87d0f1b7 | missing unit test | ReportPromptDialog.__init__ runs when people use DT but no DT test covers it | dt/report_ui.py:66 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 38 | TEST-24bcce0f | missing unit test | AssessmentBuilder.edit_unit runs when people use DT but no DT test covers it | dt/assessment_ui.py:274 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 39 | TEST-d94f825e | missing unit test | ReportReviewDialog.__init__ runs when people use DT but no DT test covers it | dt/report_ui.py:90 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 40 | TEST-ae834942 | missing unit test | MaintenanceWorker.run runs when people use DT but no DT test covers it | dt/ui.py:143 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 41 | TEST-a747ec8e | missing unit test | MainWindow.report_draft_ready runs when people use DT but no DT test covers it | dt/ui.py:1432 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 42 | TERMS-a1db32ba | copy | Mixed words for the encrypted store: 'vault' x11, 'records' x15 |  | Pick one term for users and use it everywhere. |
| 43 | TERMS-0eeffe59 | copy | Mixed words for one driver's assessment: 'assessment' x29, 'session' x3 |  | Pick one term for users and use it everywhere. |
| 44 | TERMS-9b76be63 | copy | Mixed words for evidence files: 'evidence' x24, 'recording' x4, 'video' x10 |  | Pick one term for users and use it everywhere. |
| 45 | TERMS-5a196401 | copy | Mixed words for signing: 'sign' x4, 'signature' x3 |  | Pick one term for users and use it everywhere. |
| 46 | TEST-001d6141 | missing unit test | AssessmentBuilder.edit_connection runs when people use DT but no DT test covers it | dt/assessment_ui.py:304 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 47 | TEST-fddaba56 | missing unit test | AssessmentBuilder.finish runs when people use DT but no DT test covers it | dt/assessment_ui.py:427 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 48 | TEST-f1a13250 | missing unit test | ImportWorker.run runs when people use DT but no DT test covers it | dt/ui.py:57 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 49 | TEST-d551104b | missing unit test | AnalysisWorker.run runs when people use DT but no DT test covers it | dt/ui.py:92 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 50 | TEST-20e28652 | missing unit test | MainWindow.mark_evidence_reviewed runs when people use DT but no DT test covers it | dt/ui.py:1554 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 51 | TEST-b13d3dfa | missing unit test | AssessmentBuilder.edit_parameters runs when people use DT but no DT test covers it | dt/assessment_ui.py:392 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 52 | TEST-f71ac4a5 | missing unit test | PlaybackWorker.run runs when people use DT but no DT test covers it | dt/playback_ui.py:30 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 53 | TEST-b28dbe94 | missing unit test | MainWindow.use_video_moment runs when people use DT but no DT test covers it | dt/ui.py:1683 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 54 | TEST-cbba5b93 | missing unit test | MainWindow.export runs when people use DT but no DT test covers it | dt/ui.py:1848 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 55 | TEST-b043c28f | missing unit test | AssessmentBuilder.load_template runs when people use DT but no DT test covers it | dt/assessment_ui.py:476 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 56 | TEST-33e13cb1 | missing unit test | RegistrationApprovalDialog.__init__ runs when people use DT but no DT test covers it | dt/registration_ui.py:41 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 57 | TEST-6a1d190b | missing unit test | AnalysisWorker.perform runs when people use DT but no DT test covers it | dt/ui.py:109 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 58 | TEST-56d62a6b | missing unit test | AssessmentBuilder.edit_jurisdiction runs when people use DT but no DT test covers it | dt/assessment_ui.py:324 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 59 | TEST-03540e50 | missing unit test | AssessmentBuilder.import_pack runs when people use DT but no DT test covers it | dt/assessment_ui.py:495 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 60 | TEST-b361b004 | missing unit test | MainWindow.watch_video runs when people use DT but no DT test covers it | dt/ui.py:1663 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 61 | TEST-718be90c | missing unit test | main runs when people use DT but no DT test covers it | dt/ui.py:2076 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 62 | TEST-63fb1703 | missing unit test | exclusion_dialog runs when people use DT but no DT test covers it | dt/assessment_ui.py:533 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 63 | TEST-88657e76 | missing unit test | report_input runs when people use DT but no DT test covers it | dt/report_ui.py:10 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 64 | TEST-c5edb273 | missing unit test | MainWindow.setup_report_ai runs when people use DT but no DT test covers it | dt/ui.py:1395 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
| 65 | TEST-6f4d915e | missing unit test | ReportWorker.run runs when people use DT but no DT test covers it | dt/report_ui.py:118 | Add a DT unit or desktop test; Jev scenarios show realistic inputs. |
