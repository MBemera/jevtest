# Example Jev QA report (DT)

Example output: `jev report` on a short hands-on session in which Claude Code drove DT (main at `6ead556`) through the `jev` CLI while the harness was being validated on 2026-09-29. Every item was reproduced at least twice. Real runs also attach a screenshot, snapshot and event log per finding (`evidence/`), omitted here.

**Distinct issues:** 2 high, 2 medium

| # | Severity | Category | Issue | Found by | Reports |
|---|---|---|---|---|---|
| 1 | high | functional | Typing a truck make key by key saves a corrupted value (KENWORTH becomes KENWORTHWORTH) | claude-code (via jev CLI) | 1 |
| 2 | high | data-loss | Mouse wheel over the Mark dropdown can set CF and permanently stop the session with no confirmation | claude-code (via jev CLI) | 1 |
| 3 | medium | copy | Help guide says video playback is not built in, but Evidence has in-app playback and clipping | claude-code (via jev CLI) | 1 |
| 4 | medium | ux | After Check video file finishes, the file selection is cleared, so the next evidence action fails | claude-code (via jev CLI) | 1 |

## 1. Typing a truck make key by key saves a corrupted value (KENWORTH becomes KENWORTHWORTH)

- **Severity:** high  **Category:** functional  **Source:** claude-code  **Confidence:** confirmed

**Steps to reproduce**

1. Unlock a vault, choose New assessment (1 Prepare).
2. Click Truck make and type KENWORTH one key at a time.
3. Press Tab to leave the field.

**Expected:** Truck make is KENWORTH and the note does not warn.

**Actual:** The field holds "KENWORTHWORTH" and the note says "Truck make 'KENWORTHWORTH' is not in the Australian approvals register". Typing "Ken" gives a different run-on value. The make/model/trailer-type combos use inline completion with Qt.MatchContains (MainWindow.searchable_combo in ui.py), so each key completes with the tail of any entry that merely contains the text, and the selected tail is kept when focus leaves.

## 2. Mouse wheel over the Mark dropdown can set CF and permanently stop the session with no confirmation

- **Severity:** high  **Category:** data-loss  **Source:** claude-code  **Confidence:** confirmed

**Steps to reproduce**

1. Open "Riley Ready" (all checks C) and go to 2 Assess.
2. Select check E02.02 Lights (mark C).
3. With the pointer over the Mark dropdown, turn the mouse wheel down 4 notches (as happens when scrolling the page).
4. Turn the wheel back up 3 notches, then open 4 Finalise and export.

**Expected:** Scrolling does not change marks, or CF asks for confirmation; a mark that is changed back leaves the outcome as it was.

**Actual:** Each notch changes the mark (C -> D -> NYC -> NA -> CF) and autosaves; the record becomes "stopped". After moving the mark back to D the summary still reads "STOPPED | Not yet competent ... CRITICAL EVENT" with 68/68 coverage. QComboBox wheel scrolling is enabled on Windows/Linux styles and DraftBuffer.mark keeps state "stopped" once any CF is recorded.

## 3. Help guide says video playback is not built in, but Evidence has in-app playback and clipping

- **Severity:** medium  **Category:** copy  **Source:** claude-code  **Confidence:** confirmed

**Steps to reproduce**

1. Unlock a vault and press F1 (Help guide).
2. Choose the topic "Evidence and review copies".

**Expected:** Help describes Watch video and mark assessment, Clip this moment and Install FFmpeg for video features, which exist on 3 Evidence.

**Actual:** Help says "Watch the recording in your video player, then choose Mark as reviewed ... Playback is not built into this version." and "If the app reports that FFmpeg is missing, ask your support person to configure it."

## 4. After Check video file finishes, the file selection is cleared, so the next evidence action fails

- **Severity:** medium  **Category:** ux  **Source:** claude-code  **Confidence:** confirmed

**Steps to reproduce**

1. Open an assessment with a recording policy reference; go to 3 Evidence.
2. Import drive-clip-12s-640x360.mp4 and select it in the list.
3. Click Check video file and wait for "Media validated".
4. Click Watch video and mark assessment (or Mark as reviewed).

**Expected:** The checked file stays selected so the trainer can continue with the next step on the same file.

**Actual:** The list is rebuilt with nothing selected, the detail reads "Select an imported file", and the next button shows the warning "Select an imported file first". The same happens after import and after saving clips (refresh_sessions -> populate_session clears the assets list).
