"""Scenarios, verification and the crawler against the real app (offscreen)."""

import json
import unittest
from pathlib import Path

from jev.crawler import Crawler
from jev.registry import Registry
from jev.scenarios import load_scenario, read_findings, record_scenario, run_scenario
from jev.verify import verify

from support import TempDirTestCase, requires_app


@requires_app
class ScenarioTests(TempDirTestCase):
    def test_sweep_scenario_passes_and_replays_by_label(self):
        result = run_scenario(load_scenario("sweep/02-header-help"), self.root / "sweep", quiet=True)
        self.assertTrue(result.passed, result.failures())
        replay = record_scenario(self.root / "sweep", name="replayed")
        self.assertTrue(replay["steps"])
        refs = [step for step in replay["steps"] if str(step.get("target", "")).lstrip("w").isdigit()]
        self.assertEqual(refs, [], "recorded scenarios use labels, not refs that change between runs")

    def test_known_issue_is_reproduced_and_stays_open(self):
        registry_path = self.root / "dataset" / "registry.json"
        folder, rows = verify(["JEV-0007"], out_dir=self.root / "verify", registry_path=registry_path, quiet=True)
        self.assertEqual(rows[0]["result"], "reproduced", rows)
        self.assertEqual(Registry(registry_path).issues["JEV-0007"]["status"], "open")
        findings = read_findings(Path(rows[0]["run"]))
        self.assertEqual(findings[0]["issue_id"], "JEV-0007")
        self.assertTrue((folder / "verify-summary.md").exists())


@requires_app
class MinimiseTests(TempDirTestCase):
    def test_replay_is_reduced_to_the_steps_that_matter(self):
        from jev.minimise import Minimiser
        folder_field = "Choose a device folder for encrypted driver training records."
        scenario = {"name": "padded", "app": {"seed": "none", "network": "mock"}, "steps": [
            {"do": "set_checked", "target": "Create a new vault in an empty folder", "checked": True},
            {"do": "set_checked", "target": "Create a new vault in an empty folder", "checked": False},
            {"do": "type_text", "target": folder_field, "text": "no-such-folder"},
            {"do": "press_key", "keys": "Tab"},
            {"do": "type_text", "target": "Vault passphrase", "text": "jev-synthetic-passphrase-2026", "submit": "enter"},
            {"do": "click", "target": "OK"}]}
        first = run_scenario(dict(scenario, continue_on_error=True), self.root / "full", quiet=True)
        signatures = [finding["signature"] for finding in read_findings(first.run_dir)
                      if str(finding.get("signature", "")).startswith("text@")]
        self.assertTrue(signatures, "DT shows the raw [Errno 2] text when the folder does not exist")
        result = Minimiser(scenario, signatures, self.root / "minimise", max_minutes=4).run()
        self.assertTrue(result["reproduced"])
        self.assertLessEqual(len(result["steps"]), 3, result["steps"])
        self.assertIn("no-such-folder", json.dumps(result["steps"]))


@requires_app
class CrawlerTests(TempDirTestCase):
    def test_short_crawl_explores_and_records(self):
        summary = Crawler(self.root / "crawl", steps=25, seed=3, quiet=True).run()
        self.assertGreaterEqual(summary["controls_used"], 10, summary)
        self.assertTrue((self.root / "crawl" / "crawl.json").exists())
        steps = [json.loads(line) for line in (self.root / "crawl" / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertGreaterEqual(len(steps), 25)
        self.assertTrue(any(step.get("controls") for step in steps), "every traced action lists the visible controls")
        self.assertTrue(any((step.get("target") or {}).get("key") for step in steps))


if __name__ == "__main__":
    unittest.main()
