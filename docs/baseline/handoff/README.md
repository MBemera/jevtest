# Jev handoff for DT

Built 2026-09-29T06:15:41 from 30 Jev runs against DT `6ead5563ebbf`.

Each open issue has a brief (`issues/JEV-*.md`) with what happens, how to reproduce it, where in the code to look and how to prove the fix. `issues.json` holds the same data for tools and coding agents. `scenarios/` holds replayable Jev scenarios; `evidence/` holds screenshots.

## Workflow for a fix

1. Pick the highest-ranked issue below and read its brief.
2. Fix it in DT on a branch; add a DT regression test (unit or `tests/desktop`).
3. From the Jev repository: `JEV_DT_PATH=/path/to/that/DT jev verify --issue JEV-XXXX`.
   A passing replay marks the issue fixed in Jev's registry, tied to your DT commit.
4. Later runs that see it again mark it regressed automatically.

## Open issues (ranked)

| Rank | ID | Severity | Title | Replay |
|---|---|---|---|---|
| 1 | [JEV-0001](issues/JEV-0001.md) | high | Mouse wheel over the Mark dropdown can set CF and permanently stop the session with no confirmation | yes |
| 2 | [JEV-0002](issues/JEV-0002.md) | high | Typing a truck make key by key saves a corrupted value (KENWORTH becomes KENWORTHWORTH) | yes |
| 3 | [JEV-0003](issues/JEV-0003.md) | high | Cancel report request does nothing while an AI draft is being requested | yes |
| 4 | [JEV-0009](issues/JEV-0009.md) | medium | The unlock dialog shows raw system errors ([Errno 2] No such file or directory, [Errno 36] File name too long) | yes |
| 5 | [JEV-0004](issues/JEV-0004.md) | medium | Cancel registration check does nothing while the NHVR request is running | yes |
| 6 | [JEV-0005](issues/JEV-0005.md) | medium | After Check video file finishes, the file selection is cleared, so the next evidence action fails | yes |
| 7 | [JEV-0006](issues/JEV-0006.md) | medium | Backing up into the vault folder fails with a generic message that hides the reason | yes |
| 8 | [JEV-0007](issues/JEV-0007.md) | medium | Help guide says video playback is not built in, but Evidence has in-app playback and clipping | yes |
| 9 | [JEV-0010](issues/JEV-0010.md) | medium | Checking a damaged video shows raw FFprobe output (moov atom not found, memory addresses, internal paths) | yes |
| 10 | [JEV-0008](issues/JEV-0008.md) | low | Module builder clears the module selection after excluding it, so Restore needs a reselect | yes |

Plus 55 coverage, copy, accessibility and speed items in [other-improvements.md](other-improvements.md).
