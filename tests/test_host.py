"""Integration tests: the harness driving the real DT app offscreen."""

import json
import os
import signal
import time
import unittest

from jev.session import SEED_PASSPHRASE, AppCrashed, AppSession
from jev.client import HostError
from jev.tools import ToolRunner

from support import TempDirTestCase, requires_app


def texts(result):
    return [event.get("message") or event.get("title") for event in result["events"]]


@requires_app
class FirstRunTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.session = AppSession(self.root / "app", seed="none")
        self.session.start()
        self.addCleanup(self.session.stop)

    def test_create_vault_through_the_unlock_dialog(self):
        s = self.session
        snapshot = s.call("snapshot")["text"]
        self.assertIn("DT | Open local records", snapshot)
        self.assertIn("(modal, has focus)", snapshot)
        folder = s.sandbox / "vaults" / "v1"
        s.act("type_text", target="Choose a device folder", text=str(folder), snapshot=False)
        s.act("type_text", target="Vault passphrase", text="short", snapshot=False)
        s.act("set_checked", target="Create a new vault", checked=True, snapshot=False)
        refused = s.act("click", target="Open", role="button")
        self.assertIn("Use a passphrase of at least 12 characters", texts(refused))
        self.assertIn("message box (warning)", refused["snapshot"])
        with self.assertRaises(HostError) as blocked:
            s.act("click", target="Create a new vault", snapshot=False)
        self.assertIn("modal dialog", str(blocked.exception))
        s.act("click", target="OK", snapshot=False)
        s.act("type_text", target="Vault passphrase", text="correct-horse-battery-staple", snapshot=False)
        opened = s.act("click", target="Open", role="button")
        self.assertEqual(opened["state"]["screen"], "main window")
        self.assertIn('button "New assessment"', opened["snapshot"])
        self.assertTrue((folder / "records.sqlite").exists())

    def test_vault_outside_the_sandbox_is_refused(self):
        s = self.session
        outside = self.root / "outside-vault"
        s.act("type_text", target="Choose a device folder", text=str(outside), snapshot=False)
        s.act("type_text", target="Vault passphrase", text="correct-horse-battery-staple", snapshot=False)
        s.act("set_checked", target="Create a new vault", checked=True, snapshot=False)
        result = s.act("click", target="Open", role="button", snapshot=False)
        self.assertTrue(any("[Jev sandbox]" in (text or "") for text in texts(result)))
        self.assertFalse(outside.exists())

    def test_crash_is_detected(self):
        os.kill(self.session.ready["pid"], signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
        time.sleep(0.5)
        with self.assertRaises(AppCrashed):
            self.session.call("snapshot")


@requires_app
class SampleVaultTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.runner = ToolRunner(self.root / "run", app_options={"seed": "sample", "network": "mock"})
        self.addCleanup(self.runner.stop)

    def run_tool(self, name, **arguments):
        if name in ToolRunner.ACTIONS:
            arguments.setdefault("snapshot", False)
        result = self.runner.run(name, arguments)
        self.assertFalse(result.is_error, result.text)
        return result.text

    def test_typing_editing_and_autosave(self):
        self.run_tool("click", target="New assessment")
        typed = self.run_tool("type_text", target="Driver name", text="sam synthetic", submit="tab")
        self.assertIn("Unsaved changes", typed)
        fleet = self.run_tool("type_text", target="Fleet ID", text="fleet-99 ünï 🚚")
        snapshot = self.run_tool("snapshot")
        self.assertIn('textbox "Driver name" = "Sam synthetic"', snapshot)  # capitalised on leaving the field
        self.assertIn('textbox "Fleet ID" = "fleet-99 ünï 🚚"', snapshot)  # IDs keep what was typed
        self.run_tool("wait", seconds=1)
        self.assertIn("Saved locally", self.run_tool("snapshot"))
        self.run_tool("select_option", target="Licence class", option="HC")
        self.assertIn('"HC - Heavy Combination"', self.run_tool("snapshot"))
        self.assertIn("OK: typed", fleet)

    def test_input_dialog_and_parameter(self):
        self.run_tool("select_item", target="list", item="New driver")
        opened = self.run_tool("click", target="Insert parameter")
        self.assertIn("Insert parameter", opened)
        self.run_tool("type_text", target="Parameter name", text="Odometer start", submit="enter")
        self.assertIn('textbox "Odometer start"', self.run_tool("snapshot"))

    def test_sign_export_and_read_only(self):
        self.run_tool("select_item", target="list", item="Riley Ready")
        self.run_tool("select_tab", tab="4 Finalise")
        self.run_tool("click", target="Sign assessment")
        refused = self.run_tool("click", target="Save")
        self.assertIn("Save", refused)
        self.run_tool("draw", target="Signature drawing area")
        signed = self.run_tool("click", target="Save")
        self.assertIn("Sign assessment", signed)
        self.run_tool("select_tab", tab="1 Prepare")
        blocked = self.runner.run("type_text", {"target": "Organisation", "text": "x"})
        self.assertTrue(blocked.is_error)
        self.assertIn("read-only", blocked.text)
        self.run_tool("select_tab", tab="4 Finalise")
        self.run_tool("click", target="Export PDF and manifest")
        self.run_tool("type_text", target="Who is this management export for?", text="Fleet manager", submit="enter")
        self.run_tool("type_text", target="Purpose of this export", text="Review", submit="enter")
        exported = self.run_tool("click", target="Choose folder")
        self.assertIn("Export verified", exported)
        exports = self.runner.session.sandbox / "exports"
        self.assertTrue(any(exports.rglob("*.pdf")))

    def test_mocked_ai_request_is_recorded(self):
        self.run_tool("select_item", target="list", item="Sam Synthetic")
        self.run_tool("select_tab", tab="4 Finalise")
        self.run_tool("click", target="Draft report with AI")
        self.run_tool("select_option", target="Provider", option="OpenRouter")
        self.run_tool("type_text", target="Model", text="x-ai/grok-4.7")
        self.run_tool("type_text", target="API key / Copilot access token", text="sk-or-v1-fake")
        self.run_tool("click", target="Save")
        self.assertIn("No outgoing requests", self.run_tool("network_log"))
        sent = self.run_tool("click", target="Send approved text")
        self.assertIn("network MOCK", sent)
        self.assertIn("Review AI report draft", sent)
        log = self.run_tool("network_log")
        self.assertIn("openrouter.ai", log)
        self.assertNotIn("Sam Synthetic", log)
        self.assertNotIn("sk-or-v1-fake", log)
        self.run_tool("click", target="Use reviewed draft")
        self.assertIn("Jev mock draft", self.run_tool("read_text", target="Optional report narrative"))

    def test_import_evidence_with_the_file_chooser(self):
        self.run_tool("select_item", target="list", item="Sam Synthetic")
        self.run_tool("select_tab", tab="3 Evidence")
        self.run_tool("click", target="Import original evidence")
        imported = self.run_tool("type_text", target="Path", text="notes.txt", submit="enter")
        self.assertIn("file chooser", imported)
        self.run_tool("wait", seconds=10, until="idle")
        self.assertIn("1 item", self.run_tool("snapshot"))

    def test_lock_unlock_and_restart_persistence(self):
        self.run_tool("click", target="New assessment")
        self.run_tool("type_text", target="Organisation", text="Persisted Org", submit="tab")
        self.run_tool("click", target="Lock records")
        self.assertIn("LOCKED", self.run_tool("snapshot"))
        self.run_tool("click", target="Unlock records")
        self.run_tool("type_text", target="Vault passphrase", text="wrong-passphrase-123")
        wrong = self.run_tool("click", target="Open", role="button")
        self.assertIn("wrong passphrase", wrong)
        self.run_tool("click", target="OK")
        self.run_tool("type_text", target="Vault passphrase", text=SEED_PASSPHRASE)
        self.run_tool("click", target="Open", role="button")
        restarted = self.run_tool("restart_app")
        self.assertIn("restarted", restarted)
        self.assertIn("4 items", self.run_tool("snapshot"))

    def test_layout_audit_and_screenshot(self):
        self.run_tool("resize_window", width=640, height=480)
        audit = self.run_tool("audit", kind="all")
        self.assertIn("Tab order", audit)
        shot = self.runner.run("screenshot", {"marks": True})
        self.assertTrue(shot.image.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
