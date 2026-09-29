---
description: QA the DT app with the Jev harness (usage: /qa <mission> [persona])
argument-hint: <mission> [persona]
---
Run a hands-on QA session of the DT desktop app using the `jev` MCP tools.

Mission and persona: $ARGUMENTS (missions: `jev missions`; default `explore`, persona `edge-case-hunter`).

1. Read the mission file in `jev/data/missions/` and use its `seed`, `network`, `screen` and
   `idle_timeout_ms` settings with `app_start`.
2. Work through the mission in small steps: snapshot, act, read what happened. Take screenshots when
   appearance matters and run `audit` on each new screen.
3. For every distinct problem, reproduce it once more, then call `report_issue` with numbered steps,
   expected vs actual and a severity. Harness detections (exceptions, freezes, crashes) are already
   recorded; investigate their cause in `../DT/src/dt/`.
4. Finish with `findings`, then summarise what you tested, what you found (most severe first) and
   what you could not test. The session report is written to the session folder when the MCP server
   stops.
