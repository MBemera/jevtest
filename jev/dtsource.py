"""A static index of DT's source: functions, user-visible strings and documented limitations.

The dataset uses it to point issues at code (which function shows this text, which frame
failed), to measure code coverage per function, and to list UI text that DT defines but no
tester has ever seen on screen. It reads the DT checkout (or any commit of it through git)
and never writes to it.
"""

import ast
import re
import subprocess
from pathlib import Path

from .config import dt_path

# Calls whose string arguments are shown to the user, and what kind of text they are.
UI_CALLS = {
    "QPushButton": "button", "button": "button", "QToolButton": "button", "QCheckBox": "checkbox",
    "QRadioButton": "radio", "QLabel": "label", "QGroupBox": "group", "QAction": "action",
    "setWindowTitle": "title", "addTab": "tab", "insertTab": "tab", "setPlaceholderText": "placeholder",
    "setToolTip": "tooltip", "setStatusTip": "tooltip", "showMessage": "status", "addRow": "field",
    "addItem": "option", "addItems": "option", "setHeaderLabels": "header", "setAccessibleName": "accessible-name",
    "setText": "text", "setPlainText": "text",
}
MESSAGE_BOXES = {"information", "warning", "critical", "question", "about"}
TECHNICAL_WORDS = re.compile(r"^[a-z0-9_.:/\\-]+$")


def normalise(text):
    """Comparable form of UI text: no mnemonics or ellipses, collapsed spaces, case-folded."""
    text = str(text or "").replace("&&", "\0").replace("&", "").replace("\0", "&")
    text = text.replace("…", "").replace("...", "").replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip().casefold()


def fstring_text(node):
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append("{}")
    return "".join(parts)


def call_name(node):
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return ""


class SourceIndex:
    """Functions and string literals of every module in the ``dt`` package."""

    def __init__(self, checkout=None, commit=None):
        self.checkout = Path(checkout) if checkout else dt_path()
        self.commit = commit
        self.files = {}          # "dt/ui.py" -> source text
        self.functions = []      # dicts: file, qualname, name, cls, start, end, body_start, lines
        self.strings = []        # dicts: file, line, function, text, kind, call
        self.notes = []
        if self.checkout is not None:
            self.load()

    # ----- loading --------------------------------------------------------------------
    def load(self):
        package = self.checkout / "src" / "dt"
        names = sorted(path.name for path in package.glob("*.py"))
        if self.commit:
            listed = self.git("ls-tree", "--name-only", f"{self.commit}:src/dt")
            if listed is None:
                self.notes.append(f"DT commit {self.commit[:12]} is not in the checkout; used the working tree.")
                self.commit = None
            else:
                names = sorted(name for name in listed.splitlines() if name.endswith(".py"))
        for name in names:
            key = f"dt/{name}"
            if self.commit:
                text = self.git("show", f"{self.commit}:src/dt/{name}")
            else:
                try:
                    text = (package / name).read_text(encoding="utf-8")
                except OSError:
                    text = None
            if text is None:
                continue
            self.files[key] = text
            try:
                tree = ast.parse(text, filename=key)
            except SyntaxError as error:
                self.notes.append(f"{key} could not be parsed: {error}")
                continue
            statements = coverage_statements(text, key)
            self.index_file(key, tree, statements)

    def git(self, *arguments):
        try:
            result = subprocess.run(["git", "-C", str(self.checkout), *arguments], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", "replace")

    def index_file(self, key, tree, statements):
        functions = []

        def visit(node, scope, current):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = ".".join(scope + [child.name])
                    body = child.body
                    first = body[0]
                    body_start = first.lineno
                    docstring = (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                                 and isinstance(first.value.value, str))
                    entry = {"file": key, "qualname": qualname, "name": child.name,
                             "cls": scope[-1] if scope and scope[-1][:1].isupper() else "",
                             "start": child.lineno, "end": child.end_lineno or child.lineno,
                             "body_start": body_start, "docstring_end": first.end_lineno if docstring else 0}
                    functions.append(entry)
                    visit(child, scope + [child.name], entry)
                elif isinstance(child, ast.ClassDef):
                    visit(child, scope + [child.name], current)
                else:
                    self.collect_strings(key, child, current)
                    visit(child, scope, current)

        visit(tree, [], None)
        # Executable lines of each function, without the lines of functions nested inside it.
        for entry in functions:
            span = set(range(entry["body_start"], entry["end"] + 1))
            if entry["docstring_end"]:
                span -= set(range(entry["body_start"], entry["docstring_end"] + 1))
            for other in functions:
                if other is not entry and other["start"] > entry["start"] and other["end"] <= entry["end"]:
                    span -= set(range(other["body_start"], other["end"] + 1))
            entry["lines"] = sorted(span & statements[1])
        self.functions.extend(functions)

    def collect_strings(self, key, node, function):
        where = function["qualname"] if function else ""
        if isinstance(node, ast.Call):
            name = call_name(node)
            kind = UI_CALLS.get(name)
            arguments = list(node.args)
            if name in MESSAGE_BOXES and len(arguments) >= 3:
                self.add_string(key, arguments[1], where, "title", name)
                self.add_string(key, arguments[2], where, "message", name)
                return
            if kind:
                if name in ("addTab", "insertTab") and arguments:
                    arguments = arguments[-1:]
                for argument in arguments:
                    if isinstance(argument, (ast.List, ast.Tuple)):
                        for element in argument.elts:
                            self.add_string(key, element, where, kind, name)
                    else:
                        self.add_string(key, argument, where, kind, name)
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for argument in node.exc.args[:1]:
                self.add_string(key, argument, where, "error", call_name(node.exc))

    def add_string(self, key, node, where, kind, call):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = fstring_text(node)
        else:
            return
        if len(text.strip()) < 2:
            return
        self.strings.append({"file": key, "line": node.lineno, "function": where, "text": text, "kind": kind,
                             "call": call})

    # ----- lookups --------------------------------------------------------------------
    def all_literals(self):
        """Every string constant (not only UI calls), for matching text seen on screen."""
        if getattr(self, "_literals", None) is not None:
            return self._literals
        found = {(item["file"], item["line"], item["text"]): item for item in self.strings}
        for key, text in self.files.items():
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            owners = sorted((entry for entry in self.functions if entry["file"] == key),
                            key=lambda entry: (entry["start"], -entry["end"]))
            fragments = {id(value) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
                         for value in node.values}
            for node in ast.walk(tree):
                if id(node) in fragments:
                    continue
                if isinstance(node, ast.JoinedStr):
                    value = fstring_text(node)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value
                else:
                    continue
                if len(value.strip()) < 4 or TECHNICAL_WORDS.match(value.strip()):
                    continue
                spot = (key, node.lineno, value)
                if spot in found:
                    continue
                owner = ""
                for entry in owners:
                    if entry["start"] <= node.lineno <= entry["end"]:
                        owner = entry["qualname"]  # innermost wins: later, narrower entries overwrite
                found[spot] = {"file": key, "line": node.lineno, "function": owner, "text": value, "kind": "string",
                               "call": ""}
        self._literals = list(found.values())
        return self._literals

    def function_at(self, file, line):
        best = None
        for entry in self.functions:
            if entry["file"] == file and entry["start"] <= line <= entry["end"]:
                if best is None or entry["start"] >= best["start"]:
                    best = entry
        return best

    def locate_text(self, text, limit=4):
        """Where DT defines a piece of text a tester saw: exact matches first, then partial ones."""
        wanted = normalise(text)
        if len(wanted) < 4:
            return []
        exact, partial = [], []
        pattern = None
        for item in self.all_literals():
            literal = normalise(item["text"])
            if not literal:
                continue
            if literal == wanted:
                exact.append(item)
                continue
            if "{}" in literal and len(literal.replace("{}", "").strip(" |:,.-")) >= 10:
                if pattern is None or pattern[0] != literal:
                    pieces = [re.escape(piece) for piece in literal.split("{}")]
                    pattern = (literal, re.compile("^" + ".*?".join(pieces) + "$", re.S))
                if pattern[1].match(wanted):
                    exact.append(item)
                    continue
                literal = literal.replace("{}", " ").strip()
            if len(wanted) >= 10 and wanted in literal:
                partial.append(item)
            elif len(literal) >= 14 and literal in wanted:
                partial.append(item)
        ranked = exact + sorted(partial, key=lambda item: abs(len(normalise(item["text"])) - len(wanted)))
        return ranked[:limit]

    def excerpt(self, file, line, before=4, after=6):
        text = self.files.get(file)
        if text is None:
            return ""
        lines = text.splitlines()
        start, end = max(1, line - before), min(len(lines), line + after)
        return "\n".join(f"{number:>5}  {lines[number - 1]}" for number in range(start, end + 1))

    def ui_labels(self):
        """Labels DT gives to controls, windows and tabs (what a tester could see)."""
        return [item for item in self.strings if item["kind"] in ("button", "checkbox", "radio", "tab", "title", "group",
                                                                    "action", "field")]


def coverage_statements(text, key):
    """Executable statement lines, from coverage.py's own parser when it is installed."""
    try:
        from coverage.parser import PythonParser
        parser = PythonParser(text=text, filename=key)
        parser.parse_source()
        return "coverage", set(parser.statements)
    except Exception:  # noqa: BLE001 - fall back to a plain AST walk
        pass
    lines = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "ast", lines
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and not isinstance(node, (ast.Try, ast.Global, ast.Nonlocal)) and \
                not (hasattr(ast, "TryStar") and isinstance(node, ast.TryStar)):
            lines.add(node.lineno)
    return "ast", lines


def known_limitations(checkout=None):
    """DT's own list of what is not implemented, from its README 'Scope' section."""
    checkout = Path(checkout) if checkout else dt_path()
    if checkout is None:
        return []
    try:
        readme = (checkout / "README.md").read_text(encoding="utf-8")
    except OSError:
        return []
    items = []
    match = re.search(r"Not implemented:(.*?)(?:\n\n|$)", readme, re.S)
    if match:
        body = match.group(1).split(". These are")[0]
        items += [item.strip(" .*") for item in re.split(r",\s*(?:and\s+)?|\band\b(?= a )", body) if item.strip(" .*")]
    return items


def parse_frames(text):
    """DT frames from a traceback, a faulthandler log or a formatted stack: (file, line, function)."""
    frames = []
    patterns = [r'File "([^"]+)", line (\d+), in (\S+)', r'File "([^"]+)", line (\d+) in (\S+)',
                r"^\s*(\S+\.py):(\d+) in (\S+?):"]
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", re.M):
            path = re.sub(r"/+", "/", match.group(1).replace("\\", "/"))
            if "/dt/" not in path and not path.startswith("dt/"):
                continue
            file = "dt/" + path.split("/dt/")[-1] if "/dt/" in path else path
            frames.append((file, int(match.group(2)), match.group(3)))
    return frames
