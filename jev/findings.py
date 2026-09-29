"""Findings: issues reported by a tester plus problems the harness detects on its own."""

import difflib
import json
import re
import threading
import time
from pathlib import Path

SEVERITIES = ("critical", "high", "medium", "low", "info")
CATEGORIES = ("crash", "exception", "freeze", "data-loss", "functional", "validation", "ux", "copy", "layout",
              "accessibility", "security-privacy", "performance", "other")
SEVERITY_RANK = {name: index for index, name in enumerate(SEVERITIES)}


def normalise_title(title):
    return re.sub(r"[^a-z0-9 ]+", " ", str(title).lower()).strip()


class FindingStore:
    """Append-only findings file with in-memory de-duplication of harness detections."""

    def __init__(self, path, context=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.context = dict(context or {})
        self.lock = threading.Lock()
        self.findings = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.findings.append(json.loads(line))

    def next_id(self):
        return f"F{len(self.findings) + 1:03d}"

    def add(self, finding):
        with self.lock:
            signature = finding.get("signature")
            if signature:
                for existing in self.findings:
                    if existing.get("signature") == signature:
                        existing["occurrences"] = existing.get("occurrences", 1) + 1
                        self.rewrite()
                        return existing, False
            finding = dict(finding)
            finding.setdefault("id", self.next_id())
            finding.setdefault("time", time.strftime("%Y-%m-%dT%H:%M:%S"))
            finding.setdefault("occurrences", 1)
            for key, value in self.context.items():
                finding.setdefault(key, value)
            self.findings.append(finding)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(finding, default=str) + "\n")
            return finding, True

    def rewrite(self):
        self.path.write_text("".join(json.dumps(item, default=str) + "\n" for item in self.findings), encoding="utf-8")

    def update(self, finding_id, **fields):
        with self.lock:
            for finding in self.findings:
                if finding["id"] == finding_id:
                    finding.update(fields)
                    self.rewrite()
                    return finding
        return None

    def titles(self):
        return [f"{item['id']} [{item['severity']}] {item['title']}" for item in self.findings]


def auto_findings(events, *, step=None, screen=""):
    """Turn raw host events into harness findings (exceptions, freezes, leaked errors...)."""
    found = []
    for event in events:
        kind = event.get("kind")
        base = {"source": "harness", "step": step, "screen": screen, "event_seq": event.get("seq"),
                "during": event.get("during", "")}
        if kind == "exception":
            where = event.get("location", "unknown")
            found.append(dict(base, title=f"Unhandled {event.get('type')} in {where}", severity="high",
                              category="exception", signature=event.get("signature"),
                              actual=f"{event.get('type')}: {event.get('message')}",
                              expected="The app handles the situation and tells the user what to do; no uncaught exception.",
                              details=event.get("traceback", "")))
        elif kind == "hang":
            found.append(dict(base, title="App froze: interface stopped responding", severity="high", category="freeze",
                              signature="hang@" + stack_signature(event.get("stack")),
                              actual=event.get("summary", ""), details=format_stack(event.get("stack"))))
        elif kind == "stall":
            seconds = float(event.get("seconds") or 0)
            if seconds < 2.0:
                continue
            found.append(dict(base, title=f"Interface froze for {seconds:.1f}s", category="performance",
                              severity="medium" if seconds >= 5 else "low",
                              signature="stall@" + stack_signature(event.get("stack")),
                              actual=event.get("summary", ""), details=format_stack(event.get("stack"))))
        elif kind == "suspicious_text":
            found.append(dict(base, title=f"Technical error text shown to the user ({event.get('where')})",
                              severity="medium", category="copy",
                              signature=text_signature(event.get("where", ""), event.get("text", ""),
                                                       event.get("reason", "")),
                              actual=event.get("text", ""), expected="A plain-language message that says what to do next.",
                              details=event.get("reason", "")))
        elif kind == "qt_message" and event.get("level") in ("critical", "fatal"):
            found.append(dict(base, title=f"Qt {event.get('level')}: {event.get('message', '')[:90]}", severity="medium",
                              category="other", signature="qt@" + normalise_title(event.get("message", ""))[:80],
                              actual=event.get("message", "")))
        elif kind == "qt_message" and event.get("level") == "warning":
            found.append(dict(base, title=f"Qt warning: {event.get('message', '')[:90]}", severity="low",
                              category="other", signature="qtw@" + normalise_title(event.get("message", ""))[:80],
                              actual=event.get("message", "")))
    return found


def text_signature(where, text, reason):
    """Same place and same kind of leaked error = same issue, whatever file name or number it quotes."""
    head = re.split(r"[\[:]", str(text or ""), maxsplit=1)[0]
    head = re.sub(r"\d+", "#", normalise_title(head))[:60].strip()
    return f"text@{where}|{head or reason}"


def stack_signature(stack):
    if not stack:
        return "unknown"
    app_frames = [frame for frame in stack if "/dt/" in frame.get("file", "").replace("\\", "/")]
    frame = (app_frames or stack)[-1]
    return f"{Path(frame.get('file', '')).name}:{frame.get('line')}"


def format_stack(stack):
    return "\n".join(f"  {frame.get('file')}:{frame.get('line')} in {frame.get('function')}: {frame.get('code')}"
                     for frame in (stack or [])[-12:])


# ----- reports ---------------------------------------------------------------------------
def load_run_findings(path):
    path = Path(path)
    files = [path] if path.is_file() else list(path.glob("findings.jsonl")) + list(path.glob("*/findings.jsonl"))
    items = []
    for file in files:
        for line in file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                item.setdefault("run", str(file.parent))
                items.append(item)
    return items


def cluster(findings, threshold=0.72):
    """Group findings that describe the same problem, across runs and models."""
    groups = []
    for finding in sorted(findings, key=lambda item: SEVERITY_RANK.get(item.get("severity"), 9)):
        title = normalise_title(finding.get("title", ""))
        placed = False
        for group in groups:
            lead = group[0]
            same_signature = finding.get("signature") and finding.get("signature") == lead.get("signature")
            similar = difflib.SequenceMatcher(None, title, normalise_title(lead.get("title", ""))).ratio() >= threshold
            if same_signature or (similar and finding.get("category") == lead.get("category")):
                group.append(finding)
                placed = True
                break
        if not placed:
            groups.append([finding])
    groups.sort(key=lambda group: (min(SEVERITY_RANK.get(item.get("severity"), 9) for item in group), -len(group)))
    return groups


def render_markdown(findings, *, title="Jev QA findings", intro="", base_dir=None):
    groups = cluster(findings)
    lines = [f"# {title}", ""]
    if intro:
        lines += [intro, ""]
    counts = {}
    for group in groups:
        severity = min((item.get("severity", "info") for item in group), key=lambda s: SEVERITY_RANK.get(s, 9))
        counts[severity] = counts.get(severity, 0) + 1
    lines.append("**Distinct issues:** " + (", ".join(f"{counts[s]} {s}" for s in SEVERITIES if s in counts) or "none"))
    lines.append("")
    if groups:
        lines += ["| # | Severity | Category | Issue | Found by | Reports |", "|---|---|---|---|---|---|"]
        for number, group in enumerate(groups, 1):
            lead = group[0]
            finders = sorted({item.get("model") or item.get("source", "") for item in group if item.get("model") or item.get("source")})
            lines.append(f"| {number} | {lead.get('severity')} | {lead.get('category')} | {escape(lead.get('title'))} | "
                         f"{escape(', '.join(finders))} | {sum(item.get('occurrences', 1) for item in group)} |")
        lines.append("")
    for number, group in enumerate(groups, 1):
        lead = group[0]
        lines += [f"## {number}. {lead.get('title')}", "",
                  f"- **Severity:** {lead.get('severity')}  **Category:** {lead.get('category')}  "
                  f"**Source:** {lead.get('source', 'agent')}  **Confidence:** {lead.get('confidence', 'n/a')}"]
        if lead.get("screen"):
            lines.append(f"- **Where:** {lead.get('screen')}")
        if len(group) > 1:
            lines.append("- **Also reported as:** " + "; ".join(
                f"{item.get('id')} {item.get('title')} ({item.get('model') or item.get('source')})" for item in group[1:6]))
        steps = lead.get("steps")
        if steps:
            lines += ["", "**Steps to reproduce**", ""]
            if isinstance(steps, str):
                steps = [step for step in steps.splitlines() if step.strip()]
            lines += [f"{index}. {str(step).lstrip('0123456789. ')}" for index, step in enumerate(steps, 1)]
        for label, key in (("Expected", "expected"), ("Actual", "actual")):
            if lead.get(key):
                lines += ["", f"**{label}:** {lead.get(key)}"]
        evidence = lead.get("evidence") or {}
        if evidence.get("screenshot"):
            shot = Path(evidence["screenshot"])
            if base_dir:
                try:
                    shot = shot.relative_to(base_dir)
                except ValueError:
                    pass
            lines += ["", f"![evidence]({shot.as_posix()})"]
        if lead.get("details"):
            lines += ["", "<details><summary>Details</summary>", "", "```", str(lead.get("details"))[:4000], "```",
                      "", "</details>"]
        lines.append("")
    return "\n".join(lines)


def escape(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ")
