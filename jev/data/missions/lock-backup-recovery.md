---
title: Locking, idle lock, backup, recovery and deletion
seed: sample
idle_timeout_ms: 45000
max_steps: 70
---
The idle auto-lock is shortened to 45 seconds for this session. Type into a field and let the
app idle-lock (wait), then unlock: is the edit kept? Lock with pending edits, unlock with the
wrong passphrase, then the right one. Back up the vault (to backups/, to a folder inside the
vault, to a folder that already has a backup name, cancel), run Check recovery, and delete an
assessment (cancel at confirmation, wrong passphrase, empty passphrase, correct passphrase; a
signed one too). Finally restart_app and confirm what persisted.
