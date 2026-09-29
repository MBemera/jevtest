---
title: Registration check (NHVR, mock network)
seed: sample
network: mock
max_steps: 50
---
The network is mocked. On 1 Prepare of a sample assessment, try "Check registration with NHVR"
with no setup, then "Registration check setup (optional)" with an empty key, a key containing
spaces or odd characters, then a plausible key. Check what the approval dialog says will be sent
and what network_log shows was sent. Use set_network_mock (service nhvr) for ok, not_found,
multiple, different_plate, http_401, slow (with "Cancel registration check") and injection. Try
plates that are empty, lowercase, with spaces or hyphens, too long, or with symbols. Then "Record a
registration check myself" with odd expiry values. Check the note under the fields each time,
that nothing sets a mark, and what survives lock/unlock and signing.
