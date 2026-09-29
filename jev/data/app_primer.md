# DT in brief (what the app is supposed to do)

DT is an offline desktop app (Windows, macOS, Linux; Python + Qt) that trainers use to run
employer competency assessments of heavy-vehicle drivers. Records stay on the machine in an
encrypted "vault" folder. It is a prototype: use synthetic data only.

## First run and the vault
- On launch, "DT | Open local records" asks for a folder and a passphrase. To create a vault,
  choose an empty folder, tick "Create a new vault in an empty folder" and use a passphrase of at
  least 12 characters. Reopening needs the same folder and passphrase. There is no recovery.
- "Lock records" (or 5 minutes without input) closes the vault and shows a lock screen; unlocking
  needs the same passphrase. Pending edits are held encrypted in memory while locked.

## Main window
- Header: Hide/Show panel, workspace appearance (Transport or Classic style), Help guide (F1).
- Left panel: session search, the list of assessments, "< Previous"/"Next >" (wrap around and
  follow the search filter), New assessment, New from directory, Business directory, Delete
  assessment, Back up vault, Check recovery, Lock records, Cancel current job.
- Five tabs: 1 Prepare, 2 Assess, 3 Evidence, 4 Finalise and export, 5 Findings review.
- Below 1000 px wide the panel starts hidden and replaces the tabs when shown; Assess stacks
  vertically below 1100 px; header controls wrap below about 760 px.

## 1 Prepare
Organisation, assessor, driver name/ID, licence class (dropdown of R, C, LR, MR, HR, HC, MC that
also accepts typed text), licence expiry, fleet ID, registration, configuration, scope, route
conditions, recording policy/notice reference, jurisdiction, optional truck/trailer make, model
and trailer type (from the Australian ROVER register; unlisted entries are allowed and a note says
so), registration check (NHVR lookup with approval, or record one manually), four preparation
checkboxes, "Insert parameter" (extra named fields), Save preparation, Save driver/vehicle to
directory. Name and descriptive fields get an automatic capital first letter when you leave the
field; IDs keep what you typed. "Build assessment modules / fleet scope" opens a large builder
for modular heavy-vehicle assessments (units, connections, modules, limits, validation).

## 2 Assess
68 observable checks in 15 domains. Marks: C (competent), D (developing), NYC (not yet
competent), NO (not observed, the default), NA (not applicable: needs a reason and only allowed
on some checks), CF (critical failure: needs an observation, stops the session and cannot regain
a competent outcome). Prepared observation notes and NA reasons are dropdowns that accept typed
text; "Add to observation" appends. "Save mark and next" moves on. Criterion parameters can be
added per check.

## Autosave
Edits autosave about 500 ms after typing stops and before moving between records or checks. The
status bar distinguishes "Unsaved changes | Saving shortly..." from "Saved locally | Revision N".
A failed save keeps the draft and blocks navigation, signing and closing. "Reload saved record"
asks before discarding pending edits.

## 3 Evidence
Import requires the recording policy reference first. "Import original evidence" copies and
encrypts a local file in the background (cancellable). "Check video file" parses and decodes the
opening seconds (needs FFmpeg). "Watch video and mark assessment" plays it in a dock with "Clip
this moment" (marks 10 s either side), "Use this moment in observation" and "Mark this video as
reviewed". "Mark as reviewed" records the trainer's confirmation (needs an assessor name).
"Create compressed review copy" writes a separate smaller copy; originals never change.

## 4 Finalise and export
Shows the provisional outcome, mandatory coverage and a checklist of steps remaining before
signing ("Go to next unfinished step" jumps to them). Optional AI drafting of the report narrative
("Report AI setup", "Draft report with AI - preview first"): it shows exactly what will be sent
and sends only after approval; by default no names, IDs, signatures or video are sent; a checkbox
adds observations. Then report narrative, development actions, driver comments, Save review
notes, Reload saved record, "Sign assessment" (a drawing pad: draw, Clear, Save; signing locks the
record), "Export PDF and manifest" (asks recipient, purpose and a destination; only for signed
records) and "Create correction addendum" (a linked new record for corrections).

## 5 Findings review (optional)
Needs validated evidence. "Coverage check" lists mandatory checks with no mark. Accept or reject
each suggestion; nothing ever changes a mark.

## Directories
"Save driver/vehicle to directory" stores reusable entries (needs an assessor name).
"New from directory" starts an assessment from saved entries. "Business directory" organises
companies, divisions and driver records; edits need an assessor name on the current assessment.

## Other rules worth checking
- Signed records are read-only; changes need a correction addendum.
- Delete assessment asks for confirmation and the vault passphrase; it can delete signed records.
- Back up vault writes a verified encrypted copy to a separate folder (not inside the vault).
- Check recovery reports missing/corrupt evidence and retained imports; it never deletes files.
- The three internet features (FFmpeg download, NHVR check, AI drafting) must each ask before
  sending anything.

## Known limitations (documented; do not report these as bugs)
- No passphrase recovery; installers are unsigned; no role-based access (anyone with the
  passphrase can delete anything); typing inside the 500 ms autosave window can be lost if the
  process crashes; Coverage check does not analyse video; the assessment content is an employer
  draft, not a legal instrument; all regulated jurisdiction packs are locked.
