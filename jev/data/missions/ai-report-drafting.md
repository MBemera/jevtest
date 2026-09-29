---
title: Optional AI report drafting (mock provider)
seed: sample
network: mock
max_steps: 70
---
The network is mocked: provider requests get canned answers and nothing leaves the machine.
On 4 Finalise and export of a marked assessment, open "Report AI setup": try each provider,
empty/invalid keys and model IDs, cancel, save. Use "Draft report with AI - preview first":
check that nothing is sent before you approve (network_log), what the preview contains with and
without "Include my recorded observations" (is personal data excluded by default?), editing the
text before sending, cancelling. Then use set_network_mock to try slow (and Cancel report
request), timeout, http_401, http_429, unfinished, empty, oversized, invalid_json, injection and
long_draft answers, and check each message and that no mark/outcome changes. Apply a reviewed
draft and check the narrative and that it survives reopening. Lock the app during a slow request.
