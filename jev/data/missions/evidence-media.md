---
title: Evidence import and media checks
seed: sample
max_steps: 70
---
Work in 3 Evidence on the sample assessments. First try importing before a recording policy
reference exists, then add one. Import the fixture files (see sandbox_info): the valid clips,
the portrait/rotated clip, the audio-only file, the truncated, random-bytes, empty and
mislabelled files, and the oddly named ones. For each, check what the list, detail text and
status bar say, then "Check video file", "Mark as reviewed" (with and without an assessor name),
"Create compressed review copy" at different qualities, and "Watch video and mark assessment"
(Clip this moment, Start -5s / End +5s, Remove, Save clips to evidence, Use this moment in
observation). Try "Cancel media job" during a job, importing the same file twice, and acting on
other tabs while a job runs. If FFmpeg is not available, check how clearly the app says so.
