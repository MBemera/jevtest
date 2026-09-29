import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from support import TempDirTestCase, requires_app

REPO = Path(__file__).resolve().parents[1]


class McpServerProcess:
    def __init__(self, session_dir, *options):
        env = dict(os.environ, PYTHONPATH=str(REPO))
        self.process = subprocess.Popen([sys.executable, "-m", "jev", "mcp", "--session-dir", str(session_dir), *options],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, cwd=str(REPO), env=env)
        self.next_id = 0

    def request(self, method, params=None):
        self.next_id += 1
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                             "params": params or {}}) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def notify(self, method):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def close(self):
        self.process.stdin.close()
        self.process.wait(60)
        self.process.stdout.close()
        self.process.stderr.close()


class McpProtocolTests(TempDirTestCase):
    def test_handshake_and_tool_list_without_starting_the_app(self):
        server = McpServerProcess(self.root / "session")
        self.addCleanup(server.close)
        init = server.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                             "clientInfo": {"name": "unit-test", "version": "0"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", init["result"]["capabilities"])
        server.notify("notifications/initialized")
        tools = {tool["name"]: tool for tool in server.request("tools/list")["result"]["tools"]}
        for name in ("snapshot", "click", "type_text", "report_issue", "run_qa_agents", "app_start"):
            self.assertIn(name, tools)
        self.assertNotIn("finish", tools)
        self.assertEqual(tools["click"]["inputSchema"]["required"], ["target"])
        self.assertEqual(server.request("ping")["result"], {})
        self.assertEqual(server.request("no/such")["error"]["code"], -32601)
        unknown = server.request("tools/call", {"name": "qa_runs", "arguments": {}})
        self.assertFalse(unknown["result"]["isError"])


@requires_app
class McpAppTests(TempDirTestCase):
    def test_drive_the_app_and_report(self):
        server = McpServerProcess(self.root / "session", "--seed", "sample")
        self.addCleanup(server.close)
        server.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "claude-code", "version": "test"}})
        snapshot = server.request("tools/call", {"name": "snapshot", "arguments": {}})["result"]
        self.assertIn("DT | Driver training", snapshot["content"][0]["text"])
        click = server.request("tools/call", {"name": "click", "arguments": {"target": "New assessment"}})["result"]
        self.assertFalse(click["isError"])
        shot = server.request("tools/call", {"name": "screenshot", "arguments": {}})["result"]
        self.assertEqual(shot["content"][1]["type"], "image")
        report = server.request("tools/call", {"name": "report_issue", "arguments": {
            "title": "Example", "severity": "low", "category": "ux", "steps": "1. x", "expected": "a", "actual": "b"}})
        self.assertIn("Recorded F001", report["result"]["content"][0]["text"])
        server.close()
        findings = (self.root / "session" / "findings.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(findings[0])["source"], "claude-code")
        self.assertTrue((self.root / "session" / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
