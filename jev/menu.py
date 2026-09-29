"""`jev` on its own: choose what to do from menus instead of typing commands.

Arrow keys move, Enter chooses, typing filters the list, Esc goes back and Ctrl+C leaves. Each
path through the menus ends in an ordinary jev command, which is printed before it runs, so the
menu also teaches the command line. Without an interactive terminal it asks numbered questions.
"""

import os
import shutil
import sys
import time
from dataclasses import dataclass

BACK = object()  # Esc: go back one menu


@dataclass
class Choice:
    label: str
    value: object = None
    hint: str = ""


# ----- keys ------------------------------------------------------------------------------------
SEQUENCES = {
    b"\x1b[A": "up", b"\x1b[B": "down", b"\x1b[C": "right", b"\x1b[D": "left",
    b"\x1bOA": "up", b"\x1bOB": "down", b"\x1bOC": "right", b"\x1bOD": "left",
    b"\x1b[5~": "pageup", b"\x1b[6~": "pagedown", b"\x1b[H": "home", b"\x1b[F": "end",
    b"\x1bOH": "home", b"\x1bOF": "end", b"\x1b[1~": "home", b"\x1b[4~": "end", b"\x1b[3~": "delete",
}
WINDOWS_KEYS = {"H": "up", "P": "down", "K": "left", "M": "right", "I": "pageup", "Q": "pagedown", "G": "home",
                "O": "end", "S": "delete"}


def parse_keys(data):
    """Terminal bytes to key names ('up', 'enter', ...) or single characters."""
    keys, index = [], 0
    while index < len(data):
        if data[index] == 0x1B:
            for sequence, name in SEQUENCES.items():
                if data.startswith(sequence, index):
                    keys.append(name)
                    index += len(sequence)
                    break
            else:
                if index + 1 < len(data) and data[index + 1] in (0x5B, 0x4F):  # an unknown CSI/SS3 sequence
                    end = index + 2
                    while end < len(data) and not 0x40 <= data[end] <= 0x7E:
                        end += 1
                    index = end + 1
                else:
                    keys.append("esc")
                    index += 1
            continue
        byte = data[index]
        if byte in (0x0D, 0x0A):
            keys.append("enter")
        elif byte in (0x7F, 0x08):
            keys.append("backspace")
        elif byte == 0x09:
            keys.append("tab")
        elif byte == 0x03:
            raise KeyboardInterrupt
        elif byte >= 0x20:
            length = 1 if byte < 0x80 else 2 if byte >> 5 == 0b110 else 3 if byte >> 4 == 0b1110 else 4
            keys.append(data[index:index + length].decode("utf-8", "replace"))
            index += length
            continue
        index += 1
    return keys


class Keys:
    """Reads one key at a time from a POSIX terminal or the Windows console."""

    def __init__(self):
        self.pending = []
        self.saved = None

    def __enter__(self):
        if os.name == "nt":
            enable_windows_ansi()
        else:
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)  # keys arrive one by one; Ctrl+C still interrupts
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        return False

    def read(self):
        while not self.pending:
            if os.name == "nt":
                self.pending.append(self.read_windows())
            else:
                self.pending.extend(parse_keys(os.read(self.fd, 64)))
        return self.pending.pop(0)

    @staticmethod
    def read_windows():
        import msvcrt
        char = msvcrt.getwch()
        if char in ("\x00", "\xe0"):
            return WINDOWS_KEYS.get(msvcrt.getwch(), "")
        if char == "\x03":
            raise KeyboardInterrupt
        return {"\r": "enter", "\n": "enter", "\x08": "backspace", "\x1b": "esc", "\t": "tab"}.get(
            char, char if char >= " " else "")


def enable_windows_ansi():
    """Let the Windows console understand the colour and cursor codes the menu draws with."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except (AttributeError, OSError):
        pass


# ----- drawing -----------------------------------------------------------------------------------
class Style:
    def __init__(self, enabled):
        self.enabled = enabled
        modern = os.name != "nt" or os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")
        self.pointer = "❯" if modern else ">"
        self.done = "›" if modern else ">"

    def __call__(self, code, text):
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled and text else text


def rank(choice, query):
    """0: the label starts with the query, 1: the label has every word, 2: only the hint does, None: no match."""
    words = query.casefold().split()
    label = choice.label.casefold()
    if not words:
        return 0
    if label.startswith(query.casefold().strip()):
        return 0
    if all(word in label for word in words):
        return 1
    if all(word in f"{label} {choice.hint.casefold()}" for word in words):
        return 2
    return None


def clip(text, width):
    return text if len(text) <= width else text[:max(0, width - 1)] + "…"


class Picker:
    """An arrow-key list with type-to-filter, drawn in place like a coding harness's selectors."""

    def __init__(self, title, choices, subtitle="", default=0, style=None, out=None, back_label="back"):
        self.back_label = back_label
        self.title = title
        self.choices = choices
        self.subtitle = subtitle
        self.cursor = max(0, min(default, len(choices) - 1))
        self.query = ""
        self.style = style or Style(True)
        self.out = out or sys.stdout
        self.drawn = 0

    def visible(self):
        if not self.query:
            return self.choices
        ranked = [(rank(choice, self.query), index, choice) for index, choice in enumerate(self.choices)]
        return [choice for score, _, choice in sorted(item for item in ranked if item[0] is not None)]

    def lines(self):
        width, height = shutil.get_terminal_size((100, 30))
        width = max(40, width - 1)
        shown = self.visible()
        self.cursor = max(0, min(self.cursor, len(shown) - 1)) if shown else 0
        room = max(3, height - 6)
        start = min(max(0, self.cursor - room // 2), max(0, len(shown) - room))
        style = self.style
        lines = [style("1", clip(f"? {self.title}", width))]
        if self.subtitle:
            lines.append(style("2", clip(f"  {self.subtitle}", width)))
        if self.query:
            lines.append(clip(f"  Filter: {self.query}", width) + ("" if shown else style("33", "  (no match)")))
        longest_hint = max((len(choice.hint) for choice in self.choices), default=0)
        column = min(max((len(choice.label) for choice in self.choices), default=10),
                     max(38, width - min(longest_hint, 60) - 8))
        numbered = len(self.choices) <= 9 and not self.query
        for position in range(start, min(len(shown), start + room)):
            choice = shown[position]
            current = position == self.cursor
            marker = f"{self.style.pointer} " if current else "  "
            number = f"{position + 1}. " if numbered else ""
            text = marker + number + clip(choice.label, column).ljust(column) + "  "
            hint = clip(choice.hint, max(0, width - len(text))) if choice.hint else ""
            lines.append((style("36;1", text) if current else text) + style("2", hint))
        if len(shown) > room:
            lines.append(style("2", f"  ({len(shown)} choices, {start + 1}-{min(len(shown), start + room)} shown)"))
        keys = "↑↓ move · Enter choose · type to filter · Esc back"
        if numbered:
            keys += " · 1-9 pick"
        lines.append(style("2", clip("  " + keys, width)))
        return lines

    def paint(self, lines):
        prefix = f"\r\x1b[{self.drawn}A" if self.drawn else ""
        self.out.write(prefix + "\x1b[J" + "\n".join(lines) + "\n")
        self.out.flush()
        self.drawn = len(lines)

    def finish(self, label):
        summary = f"? {self.title} " + self.style("36", f"{self.style.done} {label}")
        self.paint([summary])

    def handle(self, key):
        """Apply one key; returns a Choice, BACK, or None to keep going."""
        shown = self.visible()
        if key == "enter":
            return shown[self.cursor] if shown else None
        if key == "esc":
            if self.query:
                self.query = ""
                return None
            return BACK
        if key in ("up", "down", "pageup", "pagedown", "home", "end"):
            step = {"up": -1, "down": 1, "pageup": -8, "pagedown": 8}.get(key)
            if step is not None and shown:
                self.cursor = (self.cursor + step) % len(shown) if abs(step) == 1 else \
                    max(0, min(len(shown) - 1, self.cursor + step))
            elif key == "home":
                self.cursor = 0
            elif key == "end":
                self.cursor = max(0, len(shown) - 1)
            return None
        if key == "backspace":
            self.query = self.query[:-1]
            self.cursor = 0
            return None
        if len(key) == 1:
            if key.isdigit() and key != "0" and not self.query and len(self.choices) <= 9:
                index = int(key) - 1
                return self.choices[index] if index < len(self.choices) else None
            self.query += key
            self.cursor = 0
        return None

    def run(self, keys):
        self.out.write("\x1b[?25l")
        try:
            while True:
                self.paint(self.lines())
                result = self.handle(keys.read())
                if result is BACK:
                    self.finish(self.back_label)
                    return BACK
                if isinstance(result, Choice):
                    self.finish(result.label)
                    return result.value
        finally:
            self.out.write("\x1b[?25h")
            self.out.flush()


class UI:
    """Asks questions with the picker, or with numbered prompts when there is no terminal."""

    def __init__(self, interactive=None):
        tty = sys.stdin.isatty() and sys.stdout.isatty()
        self.interactive = tty if interactive is None else interactive
        colours = tty and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
        self.style = Style(bool(colours))

    def choose(self, title, choices, subtitle="", default=0, back_label="back"):
        if not choices:
            return BACK
        if self.interactive:
            keys = Keys()
            try:
                keys.__enter__()
            except Exception:  # noqa: BLE001 - not a real terminal after all; ask by number instead
                self.interactive = False
            else:
                try:
                    return Picker(title, choices, subtitle, default, self.style, back_label=back_label).run(keys)
                finally:
                    keys.__exit__(None, None, None)
        return self.numbered(title, choices, subtitle, default)

    @staticmethod
    def numbered(title, choices, subtitle="", default=0):
        print(f"\n{title}" + (f"\n  {subtitle}" if subtitle else ""))
        for index, choice in enumerate(choices, 1):
            print(f"  {index}. {choice.label}" + (f"  - {choice.hint}" if choice.hint else ""))
        while True:
            try:
                answer = input(f"Choose 1-{len(choices)} (Enter = {default + 1}, b = back): ").strip()
            except EOFError:
                return BACK
            if not answer:
                return choices[default].value
            if answer.lower() in ("b", "back"):
                return BACK
            if answer.isdigit() and 1 <= int(answer) <= len(choices):
                return choices[int(answer) - 1].value

    @staticmethod
    def text(prompt, default=""):
        try:
            answer = input(f"? {prompt}" + (f" [{default}]" if default else "") + ": ").strip()
        except EOFError:
            return default
        return answer or default

    def pause(self):
        try:
            input(self.style("2", "\nPress Enter to go back to the menu..."))
        except EOFError:
            pass


# ----- what the menus offer ------------------------------------------------------------------------
def display_flags(ui):
    from .config import display_available, resolve_display
    current = resolve_display()
    choices = [Choice(f"Use my setting ({current})", [], "change it with 'Display mode' in the main menu")]
    if display_available():
        choices.append(Choice("Window: watch it on screen", ["--window"], "each step is highlighted before it happens"))
    choices.append(Choice("Headless: no windows", ["--headless"], "faster; keep using the laptop"))
    return ui.choose("Where should DT run?", choices)


def with_display(ui, argv):
    flags = display_flags(ui)
    return BACK if flags is BACK else argv + flags


def seed_choice(ui, title="Start DT with"):
    return ui.choose(title, [
        Choice("Sample records", "sample", "an unlocked vault with three synthetic assessments"),
        Choice("First run", "none", "the unlock screen, before any vault exists"),
        Choice("Empty vault", "empty", "unlocked, no records yet"),
    ])


def action_campaign(ui):
    choices = [Choice("No AI testers", "0", "free: DT's tests, sweep, verify, crawlers and the dataset (15-25 min)")]
    if os.environ.get("OPENROUTER_API_KEY"):
        choices += [Choice("Add AI testers, up to $1", "1", "OpenRouter models on core and coverage-gap missions"),
                    Choice("Add AI testers, up to $3", "3"), Choice("Add AI testers, up to $5", "5"),
                    Choice("Another amount...", "custom")]
        budget = ui.choose("Include OpenRouter AI testers?", choices)
        if budget is BACK:
            return BACK
        if budget == "custom":
            budget = ui.text("Budget in US dollars", "2")
    else:
        budget = "0"
        print("  (No OPENROUTER_API_KEY, so the campaign runs without AI testers.)")
    return with_display(ui, ["campaign", "--budget", str(budget)])


def action_sweep(ui):
    return with_display(ui, ["sweep"])


def action_crawl(ui):
    seed = seed_choice(ui)
    if seed is BACK:
        return BACK
    steps = ui.choose("How far should it explore?", [
        Choice("250 steps", "250", "about 2-4 minutes headless"),
        Choice("100 steps", "100", "a quick look"),
        Choice("500 steps", "500", "a longer journey"),
    ])
    if steps is BACK:
        return BACK
    journey = str(int(time.time()) % 100000)  # a new journey each time; the command shows how to repeat it
    return with_display(ui, ["crawl", "--seed", seed, "--steps", steps, "--random-seed", journey])


def action_scenario(ui):
    from .scenarios import find_scenarios, load_scenario
    choices = []
    for path in find_scenarios():
        try:
            title = load_scenario(path).get("title", "")
        except (OSError, ValueError):
            title = ""
        choices.append(Choice(f"{path.parent.name}/{path.stem}", f"{path.parent.name}/{path.stem}", title))
    reference = ui.choose("Which scenario?", choices)
    if reference is BACK:
        return BACK
    return with_display(ui, ["scenario", "run", reference])


def issue_choices(statuses=None, only=None):
    from .registry import Registry
    rows = []
    for issue in Registry().issues.values():
        if statuses and issue.get("status") not in statuses:
            continue
        if only and not only(issue):
            continue
        rows.append(Choice(f"{issue['id']}  {issue.get('title', '')}", issue["id"],
                           f"{issue.get('status')}, {issue.get('severity')}"))
    return rows


def action_verify(ui):
    choices = [Choice("Every known issue", None, "replay each issue on this DT checkout: fixed, open or regressed")]
    choices += issue_choices(("open", "regressed", "fixed"), only=lambda issue: bool(issue.get("scenario")))
    issue = ui.choose("Which issues?", choices)
    if issue is BACK:
        return BACK
    return with_display(ui, ["verify"] + (["--issue", issue] if issue else []))


def action_ai_tester(ui):
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("  AI testers need OPENROUTER_API_KEY (put it in the environment or in .env).")
        return BACK
    from .agent.prompts import available, load_document
    missions = [Choice(name, name, load_document("missions", name)[0].get("title", "")) for name in available("missions")]
    mission = ui.choose("Which mission?", missions)
    if mission is BACK:
        return BACK
    personas = [Choice(name, name, load_document("personas", name)[0].get("title", "")) for name in available("personas")]
    persona = ui.choose("Which persona?", personas)
    if persona is BACK:
        return BACK
    model = ui.choose("Which model?", [
        Choice("Let Jev pick", "auto:1", "a current tool-capable model from OpenRouter's live list"),
        Choice("Cheapest capable", "auto-budget:1", "lowest price that can use tools"),
        Choice("Type a model ID...", "custom", "for example x-ai/grok-4.7"),
    ])
    if model is BACK:
        return BACK
    if model == "custom":
        model = ui.text("OpenRouter model ID", "x-ai/grok-4.7")
    cost = ui.choose("Spending cap for this run", [Choice("$0.50", "0.5"), Choice("$0.25", "0.25"), Choice("$1", "1"),
                                                  Choice("Another amount...", "custom")])
    if cost is BACK:
        return BACK
    if cost == "custom":
        cost = ui.text("Cap in US dollars", "0.5")
    return with_display(ui, ["run", "--model", model, "--mission", mission, "--persona", persona,
                             "--max-cost", str(cost), "--max-steps", "45"])


def action_drive(ui):
    step = ui.choose("Drive DT yourself", [
        Choice("Start DT", "start", "then use jev snapshot / click / type (or click it yourself)"),
        Choice("What is on screen now", ["snapshot"], "every control with its ref"),
        Choice("Save a screenshot", ["screenshot", "--marks", "--out", "jev-screenshot.png"], "with refs marked"),
        Choice("Stop DT", ["stop"], "and write the session report"),
    ])
    if step is BACK or isinstance(step, list):
        return step
    seed = seed_choice(ui)
    if seed is BACK:
        return BACK
    argv = with_display(ui, ["start", "--seed", seed, "--network", "mock"])
    if argv is BACK:
        return BACK
    from .config import resolve_display
    if "--headless" not in argv and resolve_display("window" if "--window" in argv else None) == "window":
        hands = ui.choose("Will you click DT yourself as well?", [
            Choice("No, only Jev", [], "your clicks and keys in DT are ignored"),
            Choice("Yes", ["--allow-input"], "your mouse and keyboard reach DT too"),
        ])
        if hands is BACK:
            return BACK
        argv += hands
    return argv


def action_dataset(ui):
    step = ui.choose("Improvement dataset", [
        Choice("Build it from all runs", ["dataset", "build"], "issues, backlog, coverage and the DT handoff"),
        Choice("Show the summary", ["dataset", "show"], "numbers and the top of the backlog"),
        Choice("Export a shareable copy", "export", "backlog, briefs and replays, without local paths"),
    ])
    if step == "export":
        return ["dataset", "export", "--to", ui.text("Folder to write", "jev-export")]
    return step


def action_issues(ui):
    step = ui.choose("Issues", [
        Choice("List open issues", ["issues"], "highest priority first"),
        Choice("Read an issue's brief", "show", "repro steps, evidence and where to look in DT"),
        Choice("Record a triage decision", "set", "for example by design, or a harness artefact"),
        Choice("Shrink an issue's repro", "minimise", "replays shorter versions until only the key steps remain"),
    ])
    if step is BACK or isinstance(step, list):
        return step
    if step == "minimise":
        from .minimise import minimisable
        choices = issue_choices(("open", "regressed"), only=lambda issue: minimisable(issue) and issue.get("scenario"))
        if not choices:
            print("  No issue needs shrinking: only issues found by the crawler or testers can be minimised.")
            return BACK
        issue = ui.choose("Which issue?", choices)
        return BACK if issue is BACK else ["minimise", issue]
    issue = ui.choose("Which issue?", issue_choices())
    if issue is BACK:
        return BACK
    if step == "show":
        return ["issues", "show", issue]
    status = ui.choose("What is it?", [
        Choice("By design", "by-design", "DT means it to work this way"),
        Choice("Known limitation", "known-limitation", "DT's README says it is not implemented"),
        Choice("Harness artefact", "harness-artefact", "caused by the test harness, not DT"),
        Choice("Won't fix", "wontfix"), Choice("Fixed", "fixed"), Choice("Still open", "open"),
    ])
    if status is BACK:
        return BACK
    note = ui.text("Note (why)", "")
    return ["issues", "set", issue, "--status", status] + (["--note", note] if note else [])


def action_display(ui):
    from .config import resolve_display
    mode = ui.choose(f"Where should DT run by default? (now: {resolve_display()})", [
        Choice("Window", "window", "on screen, each step highlighted, so you can watch"),
        Choice("Headless", "headless", "no windows; faster, and the laptop stays free"),
        Choice("Automatic", "auto", "window when a screen is available, otherwise headless"),
    ])
    return BACK if mode is BACK else ["display", mode]


def static(argv):
    return lambda ui: argv


TOP = [
    Choice("Run a full campaign", action_campaign, "DT's own tests, sweep, verify, crawlers, then the dataset"),
    Choice("Run the scripted sweep", action_sweep, "every DT feature, scripted (5-10 min)"),
    Choice("Crawl DT automatically", action_crawl, "tries every control with awkward input"),
    Choice("Run one scenario", action_scenario, "a feature journey or a known-issue check"),
    Choice("Verify known issues", action_verify, "are they fixed on this DT checkout?"),
    Choice("Run an AI tester", action_ai_tester, "an OpenRouter model on a mission, with a spending cap"),
    Choice("Drive DT yourself", action_drive, "start DT and use it with jev commands or your own mouse"),
    Choice("Improvement dataset", action_dataset, "build, show or export what the runs found"),
    Choice("Issues", action_issues, "list, read, triage or shrink issues"),
    Choice("Display mode", action_display, "window (watch on screen) or headless"),
    Choice("Check setup", static(["doctor"]), "DT, Qt, the screen, FFmpeg and the OpenRouter key"),
    Choice("Show every command", static(["--help"]), "the full command-line reference"),
    Choice("Quit", "quit"),
]


def context_line():
    from .config import dt_path, resolve_display
    checkout = dt_path()
    return (f"DT: {checkout if checkout else 'not found (set JEV_DT_PATH)'} · display: {resolve_display()} "
            f"· OpenRouter key: {'set' if os.environ.get('OPENROUTER_API_KEY') else 'not set'}")


def show_command(argv):
    return "jev " + " ".join(f'"{part}"' if (" " in part or not part) else part for part in argv)


def run_menu(ui=None, runner=None):
    from .cli import main as cli_main
    ui = ui or UI()
    runner = runner or cli_main
    while True:
        try:
            action = ui.choose("What do you want Jev to do?", TOP, subtitle=context_line(), back_label="quit")
            if action is BACK or action == "quit":
                return 0
            argv = action(ui)
        except KeyboardInterrupt:
            print()
            return 0
        if argv is BACK or argv is None:
            continue
        print(ui.style("1", f"\n▶ {show_command(argv)}") + "\n", flush=True)
        try:
            code = runner(argv)
        except SystemExit as exit:  # argparse help and errors
            code = exit.code
        except KeyboardInterrupt:
            code = 130
            print("\nStopped.")
        except Exception as error:  # noqa: BLE001 - report and return to the menu
            code = 1
            print(f"\nThat command failed: {type(error).__name__}: {error}")
        if code not in (0, None):
            print(ui.style("33", f"(exit code {code})"))
        ui.pause()
