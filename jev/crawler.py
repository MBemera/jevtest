"""Coverage-guided crawler: exercise every reachable control of DT without a model.

Each step it looks at the structured snapshot, weights every enabled control by how often it
has already been used (never-used controls first), and acts on one with realistic or hostile
input: edge-case text, every dropdown option, list rows, tabs, checkboxes, the signature pad,
file choosers and passphrase prompts. It recovers from dialogs, locks, exits and crashes on
its own. The run is seeded, so the same seed on the same DT build replays the same journey.

Everything the crawler provokes lands in the same records as any other run: steps.jsonl,
findings (exceptions, freezes, crashes, leaked error text), evidence and DT code coverage.
"""

import json
import random
import time
from collections import Counter
from pathlib import Path

from .scenarios import record_scenario
from .session import SEED_PASSPHRASE
from .tools import ToolRunner

EDGE_TEXT = [
    "", " ", "A", "Test value 123", "ÄÖÜ ñ 中文 🚚 é", "<b>bold</b><script>alert(1)</script>", "' OR 1=1 --",
    "../../etc/passwd", "C:\\Windows\\System32", "עברית العربية", "0", "-1", "9999999999999999", "2026-02-30",
    "null", "  leading and trailing  ", "%s %d {0} {name}", "\u202etxt.exe", "Line one\nLine two",
]
LONG_TEXT = "Very long input " * 40
PASSPHRASES = [SEED_PASSPHRASE] * 7 + ["wrong-passphrase-123", "", "short"]
DANGEROUS = {"delete assessment": 0.25, "lock records": 0.3, "cancel": 0.6, "close": 0.5, "no": 0.7}
CONFIRMING = ("ok", "save", "yes", "open", "choose folder", "send this plate", "send approved text",
              "use reviewed draft")
ESCAPING = ("cancel", "close", "no")


class Crawler:
    def __init__(self, out_dir, *, steps=200, seed=1, app_options=None, quiet=False, max_minutes=30.0):
        self.out_dir = Path(out_dir)
        self.steps = steps
        self.seed = seed
        self.rng = random.Random(seed)
        self.quiet = quiet
        self.max_minutes = max_minutes
        options = {"seed": "sample", "network": "mock"}
        options.update({key: value for key, value in (app_options or {}).items() if value is not None})
        self.runner = ToolRunner(self.out_dir, app_options=options, reporter="crawler",
                                 context={"model": "crawler", "mission": "crawl", "persona": f"seed-{seed}",
                                          "run": self.out_dir.name})
        self.used = Counter()
        self.seen = set()
        self.history = []
        self.modal_streak = 0
        self.last_modal = None
        self.restarts = 0

    # ----- observation -------------------------------------------------------------------
    def observe(self):
        result = self.runner.run("snapshot", {})
        nodes = (result.data or {}).get("nodes") or []
        self.note_seen(nodes)
        return nodes

    def note_seen(self, nodes):
        for node in nodes:
            if not node.get("interactive") or node.get("role") in ("text", "scroll area", "group", "dock"):
                continue
            if node.get("role") == "tabs" and node.get("options"):
                self.seen.update(f"{node['key']}#{option}" for option in node["options"])
            else:
                self.seen.add(node["key"])

    def candidates(self, nodes):
        state = self.runner.last_state or {}
        modal = (state.get("modal") or {}).get("title")
        choices = []
        for node in nodes:
            if not node.get("interactive") or not node.get("enabled") or node.get("role") in ("text", "scroll area",
                                                                                              "group", "dock"):
                continue
            if node.get("role") == "tabs" and node.get("options"):
                # Every page of a tab bar is its own place to explore.
                for option in node["options"]:
                    if option == node.get("value"):
                        continue
                    key = f"{node['key']}#{option}"
                    weight = self.weight(node, modal, key)
                    choices.append((weight, dict(node, key=key, name=option),
                                    ("select_tab", {"target": node["ref"], "tab": option})))
                continue
            action = self.action_for(node)
            if action is None:
                continue
            weight = self.weight(node, modal)
            if weight > 0:
                choices.append((weight, node, action))
        return choices

    def weight(self, node, modal, key=None):
        used = self.used[key or node["key"]]
        weight = 8.0 if used == 0 else 1.0 / (1 + used)
        name = (node.get("name") or "").strip().casefold()
        for word, factor in DANGEROUS.items():
            if name == word or name.startswith(word + " "):
                weight *= factor
        if modal:
            if self.modal_streak > 6 and name in ESCAPING:
                weight *= 20
            elif self.modal_streak > 3 and name in CONFIRMING:
                weight *= 6
            elif node.get("role") in ("textbox", "textarea", "combobox", "checkbox", "list", "tree", "canvas"):
                weight *= 2
        if node.get("role") == "tabs" and used:
            weight *= 0.5
        return weight

    def action_for(self, node):
        role, ref = node.get("role"), node.get("ref")
        name = (node.get("name") or "").casefold()
        if role == "button":
            return ("click", {"target": ref})
        if role in ("checkbox", "radio"):
            return ("set_checked", {"target": ref, "checked": not bool(node.get("value"))})
        if role == "tabs":
            count = node.get("count") or 1
            return ("select_tab", {"target": ref, "tab": str(self.rng.randrange(count))})
        if role == "canvas":
            return ("draw", {"target": ref})
        if role == "slider":
            return ("set_value", {"target": ref, "value": self.rng.randint(0, 100000)})
        if role in ("list", "tree", "table"):
            count = node.get("count") or 0
            if not count:
                return None
            mode = self.rng.choices(["select", "activate", "toggle"], [8, 1, 1])[0]
            return ("select_item", {"target": ref, "item": str(self.rng.randrange(count)), "action": mode})
        if role == "combobox":
            count = node.get("count") or 0
            if node.get("editable") and self.rng.random() < 0.4:
                return ("type_text", {"target": ref, "text": self.text_for(name), "submit": "tab"})
            if not count:
                return None
            return ("select_option", {"target": ref, "option": str(self.rng.randrange(count))})
        if role in ("textbox", "textarea"):
            if node.get("readonly"):
                return None
            text = self.passphrase() if node.get("value") == "(hidden)" or "passphrase" in name else self.text_for(name)
            arguments = {"target": ref, "text": text}
            if role == "textbox" and self.rng.random() < 0.5:
                arguments["submit"] = self.rng.choice(["tab", "enter"])
            if len(text) > 300:
                arguments["paste"] = True
            return ("type_text", arguments)
        return None

    def text_for(self, name):
        if name == "path":
            return self.rng.choice(["drive-clip-12s-640x360.mp4", "random-bytes.mp4", "empty.mp4", "notes.txt",
                                    "catalogue-exported.json", "catalogue-malformed.json", "new-folder",
                                    "../exports", "."])
        roll = self.rng.random()
        if roll < 0.08:
            return LONG_TEXT
        if roll < 0.45:
            return self.rng.choice(EDGE_TEXT)
        return self.rng.choice(["Jordan Example", "Synthetic Haulage", "FLEET-7", "XY12ZA", "2027-06-30",
                                "Checked mirrors", "Depot yard", "Alex Assessor", "Policy 7", "Trailer_1"])

    def passphrase(self):
        return self.rng.choice(PASSPHRASES)

    # ----- main loop ----------------------------------------------------------------------
    def run(self):
        started = time.time()
        self.runner.ensure_app()
        nodes = self.observe()
        for index in range(1, self.steps + 1):
            if time.time() - started > self.max_minutes * 60:
                break
            state = self.runner.last_state or {}
            modal = (state.get("modal") or {}).get("title")
            self.modal_streak = self.modal_streak + 1 if modal and modal == self.last_modal else 0
            self.last_modal = modal
            choices = self.candidates(nodes)
            if not choices:
                self.recover(index)
                nodes = self.observe()
                continue
            weights = [weight for weight, _, _ in choices]
            _, node, (tool, arguments) = self.rng.choices(choices, weights)[0]
            arguments = dict(arguments, snapshot=False, nodes=True, wait_busy=5)
            result = self.runner.run(tool, arguments)
            self.used[node["key"]] += 1
            line = describe(tool, node, arguments)
            self.history.append(line)
            if not self.quiet:
                print(f"  {index:>4} {line[:110]}{'  -> ' + result.text.splitlines()[0][:80] if result.is_error else ''}",
                      flush=True)
            if self.runner.new_findings:
                self.attach_steps(self.runner.new_findings)
            kind = (result.data or {}).get("error_kind")
            if kind in ("crash", "exited", "hang", "start"):
                self.restart(index)
                nodes = self.observe()
                continue
            nodes = (result.data or {}).get("nodes")
            if nodes:
                self.note_seen(nodes)
            else:
                nodes = self.observe()
        self.runner.stop()
        return self.summary(started)

    def recover(self, index):
        state = self.runner.last_state or {}
        if state.get("modal"):
            result = self.runner.run("close_window", {"snapshot": False})
            if not result.is_error:
                return
            self.runner.run("press_key", {"keys": "Escape", "snapshot": False})
            return
        if state.get("screen") in ("none", "") or not state.get("windows"):
            self.restart(index)

    def restart(self, index):
        self.restarts += 1
        self.history.append("(restart DT)")
        result = self.runner.run("restart_app", {})
        if result.is_error and self.restarts > 5:
            raise RuntimeError("The app keeps failing to restart: " + result.text[:300])

    def attach_steps(self, findings):
        for finding in findings:
            if finding.get("steps"):
                continue
            recent = self.history[-15:]
            lines = [f"Start DT with seed={self.runner.app_options.get('seed')}, "
                     f"network={self.runner.app_options.get('network')} (crawler seed {self.seed})"] + recent
            self.runner.store.update(finding["id"], steps=lines, confidence="likely")
            try:
                replay = record_scenario(self.out_dir, until_step=self.runner.step, name=f"repro-{finding['id']}")
                folder = self.out_dir / "repro"
                folder.mkdir(exist_ok=True)
                path = folder / f"{finding['id']}.json"
                path.write_text(json.dumps(replay, indent=2, ensure_ascii=False), encoding="utf-8")
                self.runner.store.update(finding["id"], repro_scenario=str(path))
            except (OSError, ValueError, KeyError):
                pass

    def summary(self, started):
        windows = {}
        for key in self.seen:
            window = key.split(" | ", 1)[0]
            entry = windows.setdefault(window, {"seen": 0, "used": 0})
            entry["seen"] += 1
            entry["used"] += 1 if self.used.get(key) else 0
        summary = {"kind": "crawl", "seed": self.seed, "steps": self.runner.step, "duration": round(time.time() - started, 1),
                   "controls_seen": len(self.seen), "controls_used": len(set(self.used) & self.seen),
                   "windows": dict(sorted(windows.items())), "restarts": self.restarts,
                   "findings": len(self.runner.store.findings), "app": self.runner.app_options,
                   "never_used": sorted(self.seen - set(self.used))[:300]}
        (self.out_dir / "crawl.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary


def describe(tool, node, arguments):
    label = node.get("name") or node.get("role")
    where = f" in \"{node['window']}\"" if node.get("window_role") != "window" else (
        f" on tab \"{node['tab']}\"" if node.get("tab") else "")
    if tool == "click":
        return f"Click \"{label}\"{where}"
    if tool == "type_text":
        text = arguments.get("text", "")
        shown = (text[:40] + "…") if len(text) > 40 else text
        return f"Type {json.dumps(shown, ensure_ascii=False)} into \"{label}\"{where}" + (
            f" and press {arguments['submit']}" if arguments.get("submit") else "")
    if tool == "select_option":
        return f"Choose option {arguments.get('option')} in \"{label}\"{where}"
    if tool == "select_item":
        return f"{arguments.get('action', 'select').title()} row {arguments.get('item')} in \"{label}\"{where}"
    if tool == "select_tab":
        return f"Open tab \"{arguments.get('tab')}\"{where}"
    if tool == "set_checked":
        return f"{'Tick' if arguments.get('checked') else 'Untick'} \"{label}\"{where}"
    if tool == "draw":
        return f"Draw on \"{label}\"{where}"
    return f"{tool} \"{label}\"{where}"
