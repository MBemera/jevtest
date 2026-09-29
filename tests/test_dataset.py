"""Issue registry, dataset build, verification judging, triage and campaign helpers (no app needed)."""

import json
import sqlite3
import unittest
from pathlib import Path

from jev.campaign import fit_budget, parse_unittest, write_gap_missions
from jev.config import dt_path, dt_version
from jev.dataset import build, split_key
from jev.dtsource import SourceIndex, parse_frames
from jev.registry import Registry
from jev.scenarios import ScenarioResult
from jev.triage import triage
from jev.verify import apply, judge

from support import TempDirTestCase


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class RegistryTests(TempDirTestCase):
    def test_builtin_issues_are_seeded_with_scenarios(self):
        registry = Registry(self.root / "registry.json")
        self.assertIn("JEV-0003", registry.issues)
        issue = registry.issues["JEV-0003"]
        self.assertEqual(issue["scenario"], "regressions/cancel-report-request")
        self.assertEqual(issue["verify_kind"], "expectations")
        self.assertIn("scenario@09-ai-report#cancel-report", issue["signatures"])

    def test_findings_map_to_issues_and_new_ones_get_ids(self):
        registry = Registry(self.root / "registry.json")
        regression = {"source": "scenario:cancel-report-request", "title": "whatever", "signature": "scenario@x#1"}
        self.assertEqual(registry.match(regression)["id"], "JEV-0003")
        sweep = {"source": "scenario:13-maintenance", "signature": "scenario@13-maintenance#backup-inside-vault"}
        self.assertEqual(registry.match(sweep)["id"], "JEV-0006")
        crash = {"source": "harness", "title": "Unhandled TypeError in dt/ui.py:10", "category": "exception",
                 "severity": "high", "signature": "exception@dt/ui.py:10:TypeError"}
        self.assertIsNone(registry.match(crash))
        issue = registry.create(crash)
        self.assertEqual(issue["id"], "JEV-0101")
        self.assertEqual(issue["classification"], "confirmed bug")
        self.assertEqual(issue["verify_kind"], "signature")
        registry.absorb(issue, crash, {"id": "run-1", "dt_commit": "abc"})
        other = dict(crash, title="Unhandled TypeError in dt/ui.py:11", signature="exception@dt/ui.py:11:TypeError")
        self.assertIsNone(registry.match(other), "harness findings must not merge on similar wording")
        tester = {"source": "agent", "title": "Save button does nothing on the prepare tab", "category": "functional"}
        created = registry.create(tester)
        registry.absorb(created, tester, {"id": "run-2"})
        similar = {"source": "agent", "title": "Save button does nothing on prepare tab", "category": "functional"}
        self.assertEqual(registry.match(similar)["id"], created["id"])
        registry.save()
        again = Registry(self.root / "registry.json")
        self.assertIn(created["id"], again.issues)
        self.assertEqual(again.next_id(), "JEV-0103")

    def test_duplicates_are_followed_and_regressions_detected(self):
        registry = Registry(self.root / "registry.json")
        issue = registry.create({"source": "agent", "title": "A", "category": "ux"})
        registry.issues[issue["id"]].update(status="duplicate", duplicate_of="JEV-0003")
        registry.assignments["run#F001"] = issue["id"]
        self.assertEqual(registry.match({}, "run#F001")["id"], "JEV-0003")
        registry.set_status("JEV-0004", "fixed", by="test", commit="aaaa")
        finding = {"time": "2999-01-01T00:00:00", "signature": "scenario@x#1"}
        registry.absorb(registry.issues["JEV-0004"], finding, {"id": "later", "dt_commit": "bbbbbbbbbbbb"})
        self.assertEqual(registry.issues["JEV-0004"]["status"], "regressed")


class VerifyTests(TempDirTestCase):
    def result(self, passed, steps):
        return ScenarioResult("s", "t", passed, str(self.root), 1.0, steps, [], {})

    def step(self, index, ok=True, tool_ok=True, problems=()):
        return {"index": index, "do": "click", "ok": ok, "problems": list(problems), "note": "", "optional": False,
                "tool_ok": tool_ok, "text": ""}

    def test_judge_expectation_scenarios(self):
        issue = {"verify_kind": "expectations"}
        self.assertEqual(judge(issue, self.result(True, [self.step(1)]), self.root)[0], "passed")
        failing = [self.step(1), self.step(2, ok=False, problems=["expected status 'cancelled'"])]
        self.assertEqual(judge(issue, self.result(False, failing), self.root)[0], "reproduced")
        blocked = [self.step(1, ok=False, tool_ok=False, problems=["no control 'Model'"]),
                   self.step(2, ok=False, problems=["not run: an earlier step failed"])]
        self.assertEqual(judge(issue, self.result(False, blocked), self.root)[0], "inconclusive")

    def test_judge_signature_scenarios_and_status_changes(self):
        issue = {"verify_kind": "signature", "signatures": ["exception@dt/ui.py:10:TypeError"]}
        write_jsonl(self.root / "findings.jsonl", [{"signature": "exception@dt/ui.py:10:TypeError", "title": "boom"}])
        self.assertEqual(judge(issue, self.result(False, [self.step(1)]), self.root)[0], "reproduced")
        (self.root / "findings.jsonl").unlink()
        self.assertEqual(judge(issue, self.result(True, [self.step(1)]), self.root)[0], "passed")
        registry = Registry(self.root / "registry.json")
        dt = {"commit": "c0ffee", "branch": "fix", "dirty": False}
        self.assertEqual(apply(registry, registry.issues["JEV-0007"], "passed", "ok", dt, self.root), "fixed")
        self.assertEqual(apply(registry, registry.issues["JEV-0007"], "reproduced", "again", dt, self.root), "regressed")
        self.assertEqual(len(registry.issues["JEV-0007"]["verifications"]), 2)


class FakeClient:
    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.payloads = []

    def models(self):
        return []

    def chat(self, payload):
        self.payloads.append(payload)
        return {"choices": [{"message": {"content": json.dumps(self.verdicts.pop(0))}}], "usage": {"cost": 0.001}}


class TriageTests(TempDirTestCase):
    def test_confident_verdicts_change_issues_and_are_recorded(self):
        dataset = self.root / "dataset"
        registry = Registry(dataset / "registry.json")
        first = registry.create({"source": "agent", "title": "Video preview is black", "category": "ux"})
        second = registry.create({"source": "agent", "title": "Cancel does nothing in report", "category": "functional"})
        registry.save()
        client = FakeClient([
            {"classification": "harness artefact", "severity": "low", "confidence": 0.9, "duplicate_of": None,
             "rationale": "offscreen rendering"},
            {"classification": "confirmed bug", "severity": "high", "confidence": 0.8, "duplicate_of": "JEV-0003",
             "rationale": "same as the cancel report issue"}])
        results = triage(dataset, model="test/model", client=client)
        self.assertEqual(len(results), 2)
        self.assertEqual(client.payloads[0]["provider"], {"data_collection": "deny"})
        after = Registry(dataset / "registry.json")
        self.assertEqual(after.issues[first["id"]]["status"], "harness-artefact")
        self.assertEqual(after.issues[second["id"]]["status"], "duplicate")
        self.assertEqual(after.issues[second["id"]]["duplicate_of"], "JEV-0003")
        self.assertEqual(after.issues[first["id"]]["triage"]["model"], "test/model")


class CampaignHelperTests(TempDirTestCase):
    def test_budget_trims_personas_then_models(self):
        models, missions, personas = fit_budget(["a", "b", "c"], ["m1", "m2"], ["p1", "p2"], 0.25)
        self.assertLessEqual(len(models) * len(missions) * len(personas) * 0.05, 0.25)
        self.assertEqual(personas, ["p1"])

    def test_gap_missions_are_written_from_the_backlog(self):
        dataset = self.root / "dataset"
        write_jsonl(dataset / "improvements.jsonl", [
            {"kind": "never on screen", "title": "2 label(s) from X never appeared", "detail": "button 'Edit check'",
             "where": ["dt/assessment_ui.py:208"]},
            {"kind": "untested code", "title": "No run has executed Y", "detail": "", "where": ["dt/ui.py:10"]},
            {"kind": "issue", "title": "not a gap", "where": ["dt/ui.py:1"]}])
        written = write_gap_missions(dataset, self.root / "missions", 5)
        self.assertEqual(len(written), 2)
        text = written[0].read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\ntitle: Reach untested parts of"))

    def test_unittest_output_is_parsed(self):
        output = "..F\n======\nFAIL: test_x (tests.test_core.CoreTests.test_x)\n----\nRan 3 tests in 0.5s\n\nFAILED (failures=1)\n"
        parsed = parse_unittest(output, 1)
        self.assertEqual(parsed["tests"], 3)
        self.assertEqual(parsed["failures"], ["test_x (tests.test_core.CoreTests.test_x)"])
        self.assertIn("FAILED", parsed["summary"])


@unittest.skipUnless(dt_path() is not None, "DT checkout not found (set JEV_DT_PATH)")
class DatasetBuildTests(TempDirTestCase):
    def make_runs(self):
        index = SourceIndex()
        function = next(entry for entry in index.functions if entry["qualname"] == "MainWindow.finalise_tab")
        commit = dt_version().get("commit") or "unknown"
        runs = self.root / "runs"
        agent = runs / "20260101-000000-explore-new-trainer-some-model"
        (agent / "app").mkdir(parents=True)
        (agent / "app" / "session.json").write_text(json.dumps({"dt": {"commit": commit}, "options": {"seed": "sample"},
                                                                "started": 1700000000}), encoding="utf-8")
        (agent / "app" / "coverage.json").write_text(json.dumps({"tool": "test", "files": {
            "dt/ui.py": function["lines"][:3]}}), encoding="utf-8")
        (agent / "run.json").write_text(json.dumps({"model": "some/model", "mission": "explore", "persona": "new-trainer",
                                                    "usage": {"cost": 0.01}, "stop_reason": "finished"}), encoding="utf-8")
        key = "DT | Driver training | 4 Finalise and export | button | Cancel report request"
        write_jsonl(agent / "steps.jsonl", [
            {"step": 1, "time": 1700000001, "tool": "click", "ok": True, "latency_ms": 900, "args": {"target": "w5"},
             "target": {"key": key, "name": "Cancel report request"}, "events": {"counts": {}}, "controls": [key]},
            {"step": 2, "time": 1700000002, "tool": "type_text", "ok": True, "latency_ms": 300,
             "args": {"target": "w7", "text": "<b>x</b>"},
             "target": {"key": "DT | Driver training | 1 Prepare | textbox | Driver name"},
             "events": {"counts": {"dialog": 1}, "dialogs": [{"title": "Action requires attention",
                                                               "message": "Create or select an assessment first"}]}}])
        write_jsonl(agent / "findings.jsonl", [
            {"id": "F001", "source": "agent", "model": "some/model", "title": "Cancel report request does nothing",
             "severity": "high", "category": "functional", "time": "2026-01-01T00:00:03", "step": 1,
             "steps": ["Open Finalise", "Click \"Cancel report request\""], "expected": "It cancels",
             "actual": "Nothing happens", "evidence": {"target": {"key": key, "name": "Cancel report request"}}},
            {"id": "F002", "source": "harness", "title": "Unhandled TypeError in dt/ui.py", "severity": "high",
             "category": "exception", "signature": "exception@dt/ui.py:999:TypeError", "time": "2026-01-01T00:00:04",
             "step": 2, "details": f'Traceback (most recent call last):\n  File "/x/src/dt/ui.py", line '
                                   f'{function["start"] + 2}, in finalise_tab\nTypeError: boom'}])
        return runs

    def test_build_writes_tables_backlog_and_handoff(self):
        runs = self.make_runs()
        out = self.root / "dataset"
        summary = build(out_dir=out, roots=[runs], quiet=True)
        self.assertEqual(summary["runs"]["total"], 1)
        self.assertEqual(summary["findings"], 2)
        issues = [json.loads(line) for line in (out / "issues.jsonl").read_text(encoding="utf-8").splitlines()]
        crash = next(issue for issue in issues if issue["origin"] == "harness")
        self.assertEqual(crash["code"][0]["function"], "MainWindow.finalise_tab")
        self.assertTrue(Path(crash["scenario"]).exists(), "a replay is recorded from the run's steps")
        tester = next(issue for issue in issues if issue.get("origin") == "tester")
        self.assertEqual(tester["status"], "open")
        for name in ("improvements.md", "README.md", "handoff/README.md", "handoff/issues.json", "ui_controls.csv",
                     "code_functions.csv", "inputs.csv", "copy_problems.csv", "steps.jsonl", "registry.json"):
            self.assertTrue((out / name).exists(), name)
        self.assertTrue((out / "handoff" / "issues" / f"{crash['id']}.md").exists())
        with sqlite3.connect(out / "jev-dataset.sqlite") as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"runs", "steps", "issues", "code_functions", "ui_controls", "improvements"} <= tables)
            hit = connection.execute("SELECT hit FROM code_functions WHERE function='MainWindow.finalise_tab'").fetchone()
            self.assertEqual(hit[0], 3)
        inputs = (out / "inputs.csv").read_text(encoding="utf-8")
        self.assertIn("markup/script", inputs)
        before = len(Registry(out / "registry.json").issues)
        build(out_dir=out, roots=[runs], quiet=True)
        self.assertEqual(len(Registry(out / "registry.json").issues), before, "rebuilding must not duplicate issues")

    def test_source_index_locates_text_and_frames(self):
        index = SourceIndex()
        places = index.locate_text("Cancel report request")
        self.assertTrue(any(place["function"] == "MainWindow.finalise_tab" for place in places))
        frames = parse_frames('  File "C:\\DT\\src\\dt\\ui.py", line 12, in run_action\n')
        self.assertEqual(frames, [("dt/ui.py", 12, "run_action")])
        self.assertEqual(split_key("DT | Driver training | 1 Prepare | button | Save"),
                         ["DT | Driver training", "1 Prepare", "button", "Save"])


if __name__ == "__main__":
    unittest.main()
