"""Optional: an OpenRouter model classifies issues that nobody has confirmed yet.

For each unconfirmed issue it sends the report, the code Jev located, DT's documented scope
and the harness's known blind spots, and asks for a classification (confirmed bug, UX issue,
by design, known limitation, harness artefact), a severity check and possible duplicates.
Verdicts are stored under ``triage`` in the registry; only confident ones change the issue,
and every change is recorded in its status history so a person can undo it. Requests ask
OpenRouter to route only to providers that do not keep prompts (``data_collection: deny``).
"""

import json
import re
import time
from pathlib import Path

from .dtsource import SourceIndex, known_limitations
from .registry import ACTIVE, CLASSIFICATIONS, Registry

HARNESS_LIMITS = [
    "DT runs offscreen: there is no real GPU, window manager, audio device or system tray, so video frames can "
    "render blank and nothing is audible.",
    "Native file dialogs are replaced by Jev's stand-in file chooser, limited to the sandbox folder.",
    "The network is blocked or mocked (canned NHVR and AI replies) unless a live test was requested.",
    "Fonts and pixel sizes come from Qt's offscreen platform and can differ from Windows or macOS.",
    "Input is synthetic (QTest events); drag gestures and IME input are approximations.",
]
STATUS_FOR = {"by design": "by-design", "known limitation": "known-limitation", "harness artefact": "harness-artefact"}
SYSTEM = """You triage QA findings for DT, an offline desktop app that driver trainers use to prepare, mark,
evidence, sign and export employer driving assessments. Findings come from automated testers driving the
real app in a sandbox. Decide what each finding really is. Answer with one JSON object and nothing else:
{"classification": "confirmed bug" | "ux issue" | "by design" | "known limitation" | "harness artefact",
 "severity": "critical" | "high" | "medium" | "low" | "info",
 "confidence": number from 0 to 1,
 "duplicate_of": "JEV-####" or null,
 "rationale": "one or two sentences"}
Use "harness artefact" only when the finding is explained by the test harness limits listed. Use
"known limitation" only for features DT documents as not implemented. Use "by design" only when DT's own
text clearly intends the behaviour. Prefer "ux issue" for confusing but working behaviour."""


def pick_model(client, model):
    if not model or model.startswith("auto"):
        from .agent.models import pick_models
        chosen = pick_models(client.models(), 1, budget=True)
        if not chosen:
            raise RuntimeError("No suitable OpenRouter model found for triage")
        return chosen[0]
    return model


def parse_verdict(text):
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        verdict = json.loads(match.group(0))
    except ValueError:
        return None
    if verdict.get("classification") not in CLASSIFICATIONS:
        return None
    try:
        verdict["confidence"] = max(0.0, min(1.0, float(verdict.get("confidence", 0))))
    except (TypeError, ValueError):
        verdict["confidence"] = 0.0
    return verdict


def issue_prompt(issue, row, others, index, limitations):
    lines = [f"Finding {issue['id']}: {issue.get('title')}",
             f"Reported severity: {issue.get('severity')}; category: {issue.get('category')}; "
             f"reporters: {', '.join(row.get('reporters') or []) or 'n/a'}; seen {row.get('occurrences', 1)} time(s).",
             f"Expected: {issue.get('expected') or 'n/a'}", f"Actual: {issue.get('actual') or 'n/a'}"]
    steps = row.get("steps") or []
    if steps:
        lines.append("Steps:\n" + "\n".join(f"{number}. {step}" for number, step in enumerate(steps[:20], 1)))
    for place in (row.get("code") or [])[:2]:
        excerpt = index.excerpt(place["file"], place["line"], 3, 8) if index else ""
        lines.append(f"Code near {place['file']}:{place['line']} ({place['function']}):\n{excerpt}")
    lines.append("DT documents as not implemented: " + "; ".join(limitations or ["(none listed)"]))
    lines.append("Test harness limits:\n- " + "\n- ".join(HARNESS_LIMITS))
    if others:
        lines.append("Other open issues (for duplicates):\n" + "\n".join(f"{item['id']}: {item.get('title')}"
                                                                      for item in others[:40]))
    return "\n\n".join(lines)


def triage(dataset, *, model="auto", max_cost=0.25, limit=15, apply=True, include_all=False, client=None):
    dataset = Path(dataset)
    registry = Registry(dataset / "registry.json")
    rows = {}
    if (dataset / "issues.jsonl").exists():
        for line in (dataset / "issues.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    pending = [issue for issue in registry.issues.values()
               if issue.get("status") in ACTIVE and issue.get("classification") == "unconfirmed"
               and (include_all or not issue.get("triage"))]
    pending.sort(key=lambda issue: -(rows.get(issue["id"], {}).get("score") or 0))
    if not pending:
        return []
    if client is None:
        from .agent.openrouter import OpenRouter
        client = OpenRouter()
    model = pick_model(client, model)
    index = SourceIndex()
    limitations = known_limitations()
    spent, results = 0.0, []
    for issue in pending[:limit]:
        if spent >= max_cost:
            break
        others = [item for item in registry.issues.values() if item["id"] != issue["id"] and item.get("status") in ACTIVE]
        payload = {"model": model, "temperature": 0, "max_tokens": 700, "usage": {"include": True},
                   "provider": {"data_collection": "deny"},
                   "messages": [{"role": "system", "content": SYSTEM},
                                {"role": "user", "content": issue_prompt(issue, rows.get(issue["id"], {}), others,
                                                                         index, limitations)}]}
        body = client.chat(payload)
        spent += float((body.get("usage") or {}).get("cost") or 0)
        choice = (body.get("choices") or [{}])[0]
        verdict = parse_verdict(((choice.get("message") or {}).get("content")) or "")
        result = {"id": issue["id"], "model": model}
        if verdict is None:
            result.update(classification="?", rationale="the model's answer was not valid JSON")
            results.append(result)
            continue
        result.update(verdict)
        results.append(result)
        if not apply:
            continue
        issue["triage"] = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, **verdict}
        confident = verdict["confidence"] >= 0.75
        duplicate = str(verdict.get("duplicate_of") or "").upper()
        if confident and duplicate in registry.issues and duplicate != issue["id"]:
            issue["duplicate_of"] = duplicate
            registry.set_status(issue["id"], "duplicate", by=f"triage:{model}", note=verdict.get("rationale", ""))
            continue
        if confident:
            issue["classification"] = verdict["classification"]
            status = STATUS_FOR.get(verdict["classification"])
            if status and verdict["confidence"] >= 0.85:
                registry.set_status(issue["id"], status, by=f"triage:{model}", note=verdict.get("rationale", ""))
    if apply:
        registry.save()
    return results
