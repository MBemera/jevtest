"""The OpenRouter agent loop against a scripted fake OpenRouter server and the real app."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jev.agent.openrouter import OpenRouter
from jev.agent.runner import QARun, RunConfig, compact

from support import TempDirTestCase, requires_app


def call(name, arguments, index):
    return {"id": f"call_{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


SCRIPT = [
    [call("snapshot", {}, 1)],
    [call("click", {"target": "New assessment", "snapshot": False}, 2)],
    [call("type_text", {"target": "Driver name", "text": "sam synthetic", "submit": "tab"}, 3),
     call("note", {"text": "created a record and typed a name"}, 4)],
    [call("report_issue", {"title": "Scripted issue", "severity": "low", "category": "ux",
                           "steps": "1. New assessment\n2. Type a name", "expected": "x", "actual": "y",
                           "confidence": "confirmed"}, 5)],
    [call("click", {"target": "definitely-not-a-button"}, 6)],
    [call("finish", {"summary": "Scripted run complete", "not_tested": "everything else"}, 7)],
]


class FakeOpenRouter(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = {"data": [{"id": "fake/model", "name": "Fake", "supported_parameters": ["tools", "tool_choice"],
                          "architecture": {"input_modalities": ["text"]}, "context_length": 100000}]}
        self.reply(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenRouter.requests.append({"payload": payload, "auth": self.headers.get("Authorization")})
        turn = len(FakeOpenRouter.requests) - 1
        calls = SCRIPT[turn] if turn < len(SCRIPT) else [call("finish", {"summary": "extra"}, 99)]
        self.reply({"id": f"gen-{turn}", "model": "fake/model",
                    "choices": [{"finish_reason": "tool_calls",
                                 "message": {"role": "assistant", "content": None, "tool_calls": calls}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "cost": 0.0012}})

    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class CompactTests(TempDirTestCase):
    def test_old_results_are_shortened_and_pairs_kept(self):
        history = []
        for index in range(12):
            history.append({"role": "assistant", "content": None,
                            "tool_calls": [call("snapshot", {}, index)]})
            history.append({"role": "tool", "tool_call_id": f"call_{index}",
                            "content": "OK: did it\nSnapshot after the action:\n" + "x" * 3000})
        compacted = compact(history, keep_recent=4)
        self.assertEqual(len(compacted), len(history))
        self.assertIn("[older result shortened]", compacted[1]["content"])
        self.assertLess(len(compacted[1]["content"]), 600)
        self.assertEqual(compacted[-1]["content"], history[-1]["content"])


@requires_app
class AgentLoopTests(TempDirTestCase):
    def test_scripted_model_drives_the_app_and_reports(self):
        FakeOpenRouter.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenRouter)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        client = OpenRouter(api_key="test-key", base_url=f"http://127.0.0.1:{server.server_address[1]}/api/v1",
                            attempts=1)
        config = RunConfig(model="fake/model", mission="prepare-assessment", persona="busy-assessor",
                           out_dir=str(self.root / "runs"), label="scripted", quiet=True,
                           app={"seed": "empty"})
        summary = QARun(config, client=client).execute()

        self.assertEqual(summary["stop_reason"], "the tester called finish")
        self.assertEqual(summary["tester_summary"]["summary"], "Scripted run complete")
        self.assertEqual(summary["findings"], 1)
        self.assertAlmostEqual(summary["usage"]["cost"], 0.0072, places=4)
        run_dir = self.root / "runs" / "scripted"
        findings = [json.loads(line) for line in (run_dir / "findings.jsonl").read_text().splitlines()]
        self.assertEqual(findings[0]["title"], "Scripted issue")
        self.assertEqual(findings[0]["model"], "fake/model")
        self.assertTrue((run_dir / "evidence" / "F001.png").exists())
        report = (run_dir / "report.md").read_text()
        self.assertIn("Scripted issue", report)
        self.assertIn("Experienced assessor in a hurry", report)

        first = FakeOpenRouter.requests[0]
        self.assertEqual(first["auth"], "Bearer test-key")
        self.assertIn("tools", first["payload"])
        tool_names = {tool["function"]["name"] for tool in first["payload"]["tools"]}
        self.assertTrue({"click", "report_issue", "finish", "note"} <= tool_names)
        self.assertNotIn("app_start", tool_names)
        system = first["payload"]["messages"][0]["content"]
        self.assertIn("Experienced assessor in a hurry", system)
        self.assertIn("Insert parameter", system)

        third = FakeOpenRouter.requests[3]["payload"]["messages"]
        tool_messages = [message for message in third if message["role"] == "tool"]
        self.assertTrue(any("Driver name" in message["content"] for message in tool_messages))
        self.assertIn("[Session memory]", tool_messages[-1]["content"])
        self.assertIn("created a record", tool_messages[-1]["content"])
        failed_click = FakeOpenRouter.requests[5]["payload"]["messages"][-1]["content"]
        self.assertIn("Could not do that", failed_click)
        transcript = (run_dir / "transcript.jsonl").read_text().splitlines()
        self.assertTrue(any(json.loads(line)["type"] == "tool" for line in transcript))


if __name__ == "__main__":
    unittest.main()
