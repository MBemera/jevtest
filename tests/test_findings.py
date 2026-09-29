import sys
import unittest

from jev.findings import FindingStore, auto_findings, cluster, render_markdown
from jev.host.monitor import EventLog, exception_event, raw_error_reason

from support import TempDirTestCase


class FindingTests(TempDirTestCase):
    def test_exception_events_become_deduplicated_findings(self):
        log = EventLog()
        for _ in range(2):
            try:
                {}["fleet_id"]
            except KeyError:
                exception_event(log, *sys.exc_info(), app_marker="/tests/")
        store = FindingStore(self.root / "findings.jsonl")
        for finding in auto_findings(log.since(0)):
            store.add(finding)
        self.assertEqual(len(store.findings), 1)
        self.assertEqual(store.findings[0]["occurrences"], 2)
        self.assertEqual(store.findings[0]["severity"], "high")
        self.assertIn("KeyError", store.findings[0]["title"])

    def test_raw_error_text_is_recognised(self):
        self.assertTrue(raw_error_reason("'NoneType' object has no attribute 'id'"))
        self.assertTrue(raw_error_reason("'fleet_id'"))
        self.assertTrue(raw_error_reason("[Errno 13] Permission denied: '/x'"))
        self.assertFalse(raw_error_reason("Use a passphrase of at least 12 characters"))
        self.assertFalse(raw_error_reason("OK"))

    def test_cluster_merges_similar_reports_across_models(self):
        findings = [
            {"id": "F001", "title": "Delete accepts an empty passphrase", "severity": "high", "category": "validation",
             "model": "a/one"},
            {"id": "F001", "title": "Delete accepts empty passphrase", "severity": "medium", "category": "validation",
             "model": "b/two"},
            {"id": "F002", "title": "Help text mentions no playback", "severity": "low", "category": "copy",
             "model": "a/one"},
        ]
        groups = cluster(findings)
        self.assertEqual(len(groups), 2)
        report = render_markdown(findings)
        self.assertIn("a/one, b/two", report)
        self.assertIn("Distinct issues:** 1 high, 1 low", report)


if __name__ == "__main__":
    unittest.main()
