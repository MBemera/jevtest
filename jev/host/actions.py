"""Realistic input actions: every action is delivered as mouse and keyboard events.

Actions refuse what a person could not do either: touching an invisible widget, a
disabled widget, or anything behind an open modal dialog. Input is scheduled on the
event loop rather than run inline, so an action that opens a modal dialog (which starts
a nested event loop) does not block the harness.
"""

import traceback

import shiboken6
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QKeySequence, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractScrollArea, QAbstractSlider, QApplication, QCheckBox,
    QComboBox, QDialog, QLineEdit, QListView, QListWidget, QPlainTextEdit, QRadioButton,
    QScrollArea, QTabWidget, QTextEdit, QTreeWidget, QWidget,
)

from .describe import LabelIndex, clean, name_of, role_of

LEFT = Qt.MouseButton.LeftButton
NO_MODIFIER = Qt.KeyboardModifier.NoModifier
TYPE_CHUNK = 1  # one key per event-loop turn, so completers and validators react as they do for a person
MAX_TYPED_CHARACTERS = 600
DEFAULT_SIGNATURE = [
    [[0.08, 0.62], [0.14, 0.40], [0.20, 0.66], [0.27, 0.35], [0.33, 0.68], [0.40, 0.42], [0.47, 0.60]],
    [[0.52, 0.55], [0.60, 0.38], [0.66, 0.64], [0.74, 0.44], [0.82, 0.58], [0.92, 0.50]],
]


class ActionError(Exception):
    """The action cannot be performed as requested; the message says why."""


class Sequence:
    """One scheduled input sequence. ``done`` turns true when its last step has returned."""

    def __init__(self, label, steps):
        self.label = label
        self.steps = list(steps)
        self.index = 0
        self.done = False


class InputScheduler:
    """Runs an input sequence one step per event-loop turn.

    A step can open a modal dialog and then sit inside that dialog's event loop until the
    dialog closes, so completion is tracked per sequence rather than with a global counter.
    """

    def __init__(self, log):
        self.log = log
        self.last = None

    def run(self, steps, label):
        sequence = Sequence(label, steps)
        self.last = sequence

        def finish():
            sequence.done = True
            sequence.steps = []  # drop widget references held by the step closures

        def advance():
            if sequence.index >= len(sequence.steps):
                finish()
                return
            step = sequence.steps[sequence.index]
            sequence.index += 1
            try:
                step()
            except Exception as error:  # a harness-side failure, not an app bug
                finish()
                self.log.emit("harness_error", action=label, error=repr(error),
                              traceback=traceback.format_exc(limit=6))
                return
            QTimer.singleShot(0, advance)

        QTimer.singleShot(0, advance)
        return sequence


def normalise(text):
    return clean(text).casefold()


class Actions:
    def __init__(self, refs, snapshotter, scheduler, log):
        self.refs = refs
        self.snapshotter = snapshotter
        self.scheduler = scheduler
        self.log = log

    # ----- target resolution ---------------------------------------------------------
    def interactive_windows(self):
        modal = QApplication.activeModalWidget()
        windows = self.snapshotter.windows()
        if modal is not None:
            return [window for window in windows if window is modal or modal.isAncestorOf(window)]
        return windows

    def resolve(self, args, roles=None):
        ref = args.get("ref") or args.get("target")
        if ref and str(ref).strip().lstrip("[").startswith("w") and str(ref).strip().lstrip("[").rstrip("]")[1:].isdigit():
            widget = self.refs.find(ref)
            if widget is None:
                raise ActionError(f"No widget with reference {ref} exists any more. Take a new snapshot.")
            return widget
        name = args.get("name") or ref
        wanted_roles = [args["role"]] if args.get("role") else roles
        if not name and wanted_roles:
            try:
                return self.find_by_role(wanted_roles, int(args.get("index", 0)))
            except LookupError as error:
                raise ActionError(str(error)) from None
        if not name:
            raise ActionError("Give a target: ref (for example w12) or name (the visible label).")
        if str(name).strip().lower() in ("list", "tree", "tabs", "table", "canvas") and not args.get("role"):
            try:
                return self.find_by_role([str(name).strip().lower()], int(args.get("index", 0)),
                                         unique="index" not in args)
            except LookupError:
                pass
        return self.find_by_name(str(name), wanted_roles, int(args.get("index", 0)), args.get("window"))

    def find_by_role(self, roles, index=0, unique=False):
        matches = []
        for window in self.interactive_windows():
            labels = LabelIndex([window])
            matches.extend(node.widget for node in self.snapshotter.collect(window, labels) if node.role in roles)
        if not matches:
            raise LookupError(f"No visible {'/'.join(roles)} to act on.")
        if unique and len(matches) > 1:
            listed = "; ".join(self.describe(widget) for widget in matches[:6])
            raise ActionError(f"{len(matches)} {'/'.join(roles)} widgets are visible ({listed}). Use a ref.")
        if index >= len(matches):
            raise ActionError(f"Only {len(matches)} visible {'/'.join(roles)} widget(s); index {index} is out of range.")
        return matches[index]

    def find_by_name(self, name, roles, index, window_hint=None):
        wanted = normalise(name)
        windows = self.interactive_windows()
        if window_hint:
            windows = [window for window in windows if normalise(window_hint) in normalise(window.windowTitle())] or windows
        exact, prefix, contains = [], [], []
        for window in windows:
            labels = LabelIndex([window])
            nodes = self.snapshotter.collect(window, labels)
            for node in nodes:
                if roles and node.role not in roles:
                    continue
                label = normalise(node.name if node.role != "text" else node.widget.text())
                if not label:
                    continue
                if label == wanted:
                    exact.append(node.widget)
                elif label.startswith(wanted):
                    prefix.append(node.widget)
                elif wanted in label:
                    contains.append(node.widget)
        def preference(widget):
            role = role_of(widget)
            return 0 if role not in ("group", "dock", "tabs", "text", "document", "scroll area") else 1

        for group in (exact, prefix, contains):
            group.sort(key=preference)
            if group:
                if index >= len(group):
                    raise ActionError(f"Only {len(group)} match(es) for {name!r}; index {index} is out of range.")
                if len(group) > 1 and index == 0:
                    interactive = [widget for widget in group if widget.isEnabled()]
                    if interactive:
                        group = interactive
                return group[index]
        scope = "the open modal dialog" if QApplication.activeModalWidget() else "the visible windows"
        raise ActionError(f"Nothing named {name!r}{' with role ' + '/'.join(roles) if roles else ''} "
                          f"is visible in {scope}. Take a snapshot and use a ref.")

    def describe(self, widget):
        return self.snapshotter.describe(widget)

    def check_reachable(self, widget, *, need_enabled=True):
        if not shiboken6.isValid(widget):
            raise ActionError("That widget no longer exists. Take a new snapshot.")
        if not widget.isVisible():
            raise ActionError(f"{self.describe(widget)} is not visible on screen.")
        modal = QApplication.activeModalWidget()
        window = widget.window()
        if modal is not None and window is not modal and not modal.isAncestorOf(window):
            raise ActionError(f"{self.describe(widget)} is behind the modal dialog "
                              f"{modal.windowTitle()!r}. Respond to that dialog first.")
        if need_enabled and not widget.isEnabled():
            raise ActionError(f"{self.describe(widget)} is disabled, so clicking or typing does nothing.")
        notes = []
        popup = QApplication.activePopupWidget()
        if popup is not None and popup is not window and not popup.isAncestorOf(widget):
            popup.close()
            notes.append("closed an open popup first, as clicking elsewhere would")
        if self.scroll_into_view(widget):
            notes.append("scrolled it into view")
        covering = self.covering_widget(widget)
        if covering is not None:
            notes.append(f"warning: its centre is covered by {self.describe(covering)}")
            self.log.emit("layout_warning", target=self.describe(widget),
                          problem=f"centre covered by {self.describe(covering)}")
        return notes

    @staticmethod
    def scroll_into_view(widget):
        moved = False
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea) and parent.widget() is not None and parent.widget().isAncestorOf(widget):
                before = (parent.verticalScrollBar().value(), parent.horizontalScrollBar().value())
                parent.ensureWidgetVisible(widget, 20, 20)
                moved = moved or before != (parent.verticalScrollBar().value(), parent.horizontalScrollBar().value())
            parent = parent.parentWidget()
        return moved

    @staticmethod
    def covering_widget(widget):
        window = widget.window()
        centre = widget.mapTo(window, widget.rect().center())
        found = window.childAt(centre)
        if found is None or found is widget or widget.isAncestorOf(found) or found.isAncestorOf(widget):
            return None
        if isinstance(widget, QComboBox) or isinstance(found.parentWidget(), QAbstractScrollArea):
            return None
        return found

    def activate(self, widget):
        window = widget.window()
        if not window.isActiveWindow():
            window.activateWindow()

    # ----- actions -------------------------------------------------------------------
    def perform(self, name, args):
        handler = getattr(self, "do_" + name, None)
        if handler is None:
            raise ActionError(f"Unknown action {name!r}")
        return handler(args)

    def do_click(self, args):
        widget = self.resolve(args)
        if isinstance(widget, (QListView, QTreeWidget)) and "item" in args:
            return self.do_select_item(args)
        notes = self.check_reachable(widget)
        button = {"left": LEFT, "right": Qt.MouseButton.RightButton,
                  "middle": Qt.MouseButton.MiddleButton}.get(args.get("button", "left"), LEFT)
        target, position = self.click_point(widget)
        handle = self.refs.handle(target)
        description = self.describe(widget)
        double = bool(args.get("double"))
        self.activate(widget)

        def click():
            live = handle.get()
            if live is not None:
                QTest.mouseClick(live, button, NO_MODIFIER, position)

        def double_click():
            live = handle.get()
            if live is not None:
                QTest.mouseDClick(live, button, NO_MODIFIER, position)

        self.scheduler.run([click, double_click] if double else [click], f"click {description}")
        return {"did": f"{'double-' if double else ''}clicked {description}", "notes": notes}

    @staticmethod
    def click_point(widget):
        if isinstance(widget, QAbstractScrollArea) and not isinstance(widget, QComboBox):
            viewport = widget.viewport()
            return viewport, viewport.rect().center()
        return widget, widget.rect().center()

    def text_target(self, widget):
        if isinstance(widget, QComboBox):
            if not widget.isEditable():
                raise ActionError(f"{self.describe(widget)} is a fixed dropdown; use select_option.")
            return widget.lineEdit()
        if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return widget
        raise ActionError(f"{self.describe(widget)} does not accept typed text.")

    def do_type_text(self, args):
        widget = self.resolve(args)
        field = self.text_target(widget)
        notes = self.check_reachable(widget)
        if getattr(field, "isReadOnly", lambda: False)():
            raise ActionError(f"{self.describe(widget)} is read-only; typing changes nothing.")
        text = str(args.get("text", ""))
        repeat = max(1, min(int(args.get("repeat", 1) or 1), 100000))
        text = text * repeat
        multiline = isinstance(field, (QTextEdit, QPlainTextEdit))
        if not multiline and ("\n" in text or "\r" in text):
            notes.append("single-line field: line breaks were removed, as a real paste would do")
            text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        paste = bool(args.get("paste")) or len(text) > MAX_TYPED_CHARACTERS
        if paste and not args.get("paste"):
            notes.append(f"{len(text)} characters: pasted instead of typed key by key")
        clear = args.get("clear", True)
        submit = (args.get("submit") or "").lower()
        description = self.describe(widget)
        self.activate(widget)
        handle = self.refs.handle(field)

        def focus():
            live = handle.get()
            if multiline:
                QTest.mouseClick(live.viewport(), LEFT, NO_MODIFIER, QPoint(5, 5))
            else:
                QTest.mouseClick(live, LEFT, NO_MODIFIER, live.rect().center())

        def key(code, modifier=NO_MODIFIER):
            return lambda: QTest.keyClick(handle.get(), code, modifier)

        steps = [focus]
        if clear:
            steps += [key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier), key(Qt.Key.Key_Delete)]
        else:
            steps.append(key(Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier if multiline else NO_MODIFIER))
        if paste:
            def paste_text():
                QApplication.clipboard().setText(text)
                QTest.keyClick(handle.get(), Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            steps.append(paste_text)
        else:
            for start in range(0, len(text), TYPE_CHUNK):
                chunk = text[start:start + TYPE_CHUNK]
                steps.append(lambda chunk=chunk: type_characters(handle.get(), chunk))
        if submit in ("enter", "return"):
            steps.append(key(Qt.Key.Key_Return))
        elif submit == "tab":
            steps.append(key(Qt.Key.Key_Tab))
        self.scheduler.run(steps, f"type into {description}")
        verb = "pasted" if paste else "typed"
        return {"did": f"{verb} {len(text)} characters into {description}"
                       f"{' after clearing it' if clear else ''}{' then pressed ' + submit if submit else ''}",
                "notes": notes}

    def do_select_option(self, args):
        widget = self.resolve(args, roles=["combobox"])
        if not isinstance(widget, QComboBox):
            raise ActionError(f"{self.describe(widget)} is not a dropdown.")
        notes = self.check_reachable(widget)
        option = args.get("option", args.get("value"))
        index = self.combo_index(widget, option)
        description = self.describe(widget)
        text = clean(widget.itemText(index)) or "(blank)"
        self.activate(widget)
        handle = self.refs.handle(widget)

        def open_popup():
            handle.get().showPopup()

        def choose():
            widget = handle.get()
            view = widget.view()
            if not view.isVisible():
                widget.setCurrentIndex(index)
                widget.activated.emit(index)
                return
            model_index = widget.model().index(index, widget.modelColumn(), widget.rootModelIndex())
            view.scrollTo(model_index)
            QTest.mouseClick(view.viewport(), LEFT, NO_MODIFIER, view.visualRect(model_index).center())

        def verify():
            widget = handle.get()
            if widget.currentIndex() != index:
                widget.hidePopup()
                self.log.emit("harness_note", note=f"dropdown popup click did not select {text!r}; "
                                                   "selected it by keyboard instead")
                widget.setCurrentIndex(index)
                widget.activated.emit(index)

        self.scheduler.run([open_popup, choose, verify], f"select {text} in {description}")
        return {"did": f"opened {description} and chose {text!r}", "notes": notes}

    @staticmethod
    def combo_index(combo, option):
        count = combo.count()
        if option is None:
            raise ActionError("Give the option to choose (its text or its index).")
        if isinstance(option, int) or (isinstance(option, str) and option.strip().lstrip("-").isdigit()
                                       and not any(clean(combo.itemText(i)) == option.strip() for i in range(count))):
            index = int(option)
            if not 0 <= index < count:
                raise ActionError(f"Option index {index} is out of range (0..{count - 1}).")
            return index
        wanted = normalise(option)
        texts = [normalise(combo.itemText(i)) for i in range(count)]
        for matcher in (lambda text: text == wanted, lambda text: text.startswith(wanted), lambda text: wanted in text):
            for index, text in enumerate(texts):
                if matcher(text):
                    return index
        listed = ", ".join(repr(clean(combo.itemText(i))) for i in range(min(count, 30)))
        raise ActionError(f"No option matching {option!r}. Options: {listed}"
                          f"{' …' if count > 30 else ''}. An editable dropdown also accepts type_text.")

    def do_set_checked(self, args):
        widget = self.resolve(args, roles=["checkbox", "radio", "button"])
        if not isinstance(widget, QAbstractButton) or not (widget.isCheckable() or isinstance(widget, (QCheckBox, QRadioButton))):
            raise ActionError(f"{self.describe(widget)} cannot be checked or unchecked.")
        wanted = bool(args.get("checked", True))
        if widget.isChecked() == wanted:
            return {"did": f"{self.describe(widget)} was already {'checked' if wanted else 'unchecked'}; nothing done",
                    "notes": []}
        notes = self.check_reachable(widget)
        self.activate(widget)
        handle = self.refs.handle(widget)
        self.scheduler.run([lambda: QTest.mouseClick(handle.get(), LEFT, NO_MODIFIER, handle.get().rect().center())],
                           f"toggle {self.describe(widget)}")
        return {"did": f"clicked {self.describe(widget)} to {'check' if wanted else 'uncheck'} it", "notes": notes}

    def do_select_item(self, args):
        widget = self.resolve(args, roles=["list", "tree", "table"])
        if isinstance(widget, QTreeWidget):
            return self.select_tree_item(widget, args)
        if not isinstance(widget, QAbstractItemView):
            raise ActionError(f"{self.describe(widget)} is not a list.")
        notes = self.check_reachable(widget)
        model = widget.model()
        rows = model.rowCount(widget.rootIndex())
        item = args.get("item")
        row = self.find_row(widget, item, rows)
        index = model.index(row, 0, widget.rootIndex())
        if isinstance(widget, QListView) and widget.isRowHidden(row):
            raise ActionError(f"Row {row} is hidden (filtered out), so it cannot be clicked.")
        if not (model.flags(index) & Qt.ItemFlag.ItemIsEnabled):
            raise ActionError(f"Row {row} is disabled.")
        mode = (args.get("mode") or "select").lower()
        label = clean(index.data(Qt.ItemDataRole.DisplayRole))[:80]
        description = self.describe(widget)
        self.activate(widget)
        handle = self.refs.handle(widget)

        def position():
            view = handle.get()
            model_index = view.model().index(row, 0, view.rootIndex())
            view.scrollTo(model_index)
            return view, view.visualRect(model_index).center()

        def click():
            view, point = position()
            QTest.mouseClick(view.viewport(), LEFT, NO_MODIFIER, point)

        def double_click():
            view, point = position()
            QTest.mouseDClick(view.viewport(), LEFT, NO_MODIFIER, point)

        steps = [click]
        if mode in ("activate", "double_click", "open"):
            steps.append(double_click)
        elif mode in ("check", "uncheck", "toggle"):
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            if state is None:
                raise ActionError(f"Row {row} has no checkbox.")
            checked = Qt.CheckState(state) == Qt.CheckState.Checked
            if mode == "toggle" or (mode == "check") != checked:
                steps.append(lambda: QTest.keyClick(handle.get().viewport(), Qt.Key.Key_Space))
        self.scheduler.run(steps, f"{mode} row {row} in {description}")
        return {"did": f"{mode} row {row} {label!r} in {description}", "notes": notes}

    @staticmethod
    def find_row(view, item, rows):
        if item is None:
            raise ActionError("Give the item: its row number or its visible text.")
        if isinstance(item, int) or (isinstance(item, str) and item.strip().isdigit()):
            row = int(item)
            if not 0 <= row < rows:
                raise ActionError(f"Row {row} is out of range (0..{rows - 1}).")
            return row
        wanted = normalise(item)
        model = view.model()
        texts = [normalise(model.index(row, 0, view.rootIndex()).data(Qt.ItemDataRole.DisplayRole)) for row in range(rows)]
        for matcher in (lambda text: text == wanted, lambda text: text.startswith(wanted), lambda text: wanted in text):
            for row, text in enumerate(texts):
                if matcher(text) and not (isinstance(view, QListView) and view.isRowHidden(row)):
                    return row
        raise ActionError(f"No visible row matching {item!r}.")

    def select_tree_item(self, tree, args):
        notes = self.check_reachable(tree)
        wanted = args.get("item") or args.get("path")
        if wanted is None:
            raise ActionError("Give the tree item text, or a path such as 'Company / Division / Driver'.")
        target = self.find_tree_item(tree, str(wanted))
        mode = (args.get("mode") or "select").lower()
        description = self.describe(tree)
        self.activate(tree)
        handle = self.refs.handle(tree)

        def point():
            live = handle.get()
            item = self.find_tree_item(live, str(wanted))
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            live.scrollToItem(item)
            return live.viewport(), live.visualItemRect(item).center()

        def click():
            viewport, position = point()
            QTest.mouseClick(viewport, LEFT, NO_MODIFIER, position)

        def double_click():
            viewport, position = point()
            QTest.mouseDClick(viewport, LEFT, NO_MODIFIER, position)

        steps = [click]
        if mode in ("activate", "double_click", "open"):
            steps.append(double_click)
        self.scheduler.run(steps, f"{mode} tree item in {description}")
        return {"did": f"{mode} {clean(target.text(0))!r} in {description}", "notes": notes}

    @staticmethod
    def find_tree_item(tree, wanted):
        parts = [normalise(part) for part in wanted.replace(">", "/").split("/") if part.strip()]
        items = []

        def walk(item, path):
            items.append((path + [normalise(item.text(0))], item))
            for index in range(item.childCount()):
                walk(item.child(index), path + [normalise(item.text(0))])

        for index in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(index), [])
        for path, item in items:
            if len(parts) > 1 and path[-len(parts):] == parts:
                return item
        for matcher in (lambda text: text == parts[-1], lambda text: parts[-1] in text):
            for path, item in items:
                if matcher(path[-1]):
                    return item
        raise ActionError(f"No tree item matching {wanted!r}.")

    def do_select_tab(self, args):
        tab = args.get("tab")
        if tab is None:
            raise ActionError("Give the tab: its label or its index.")
        widget = self.resolve(args, roles=["tabs"]) if (args.get("ref") or args.get("name")) else self.find_tab_widget(tab)
        if not isinstance(widget, QTabWidget):
            raise ActionError(f"{self.describe(widget)} is not a set of tabs.")
        self.check_reachable(widget, need_enabled=True)
        index = self.tab_index(widget, tab)
        if not widget.isTabEnabled(index):
            raise ActionError(f"Tab {clean(widget.tabText(index))!r} is disabled.")
        handle = self.refs.handle(widget)
        self.activate(widget)

        def click():
            bar = handle.get().tabBar()
            QTest.mouseClick(bar, LEFT, NO_MODIFIER, bar.tabRect(index).center())

        self.scheduler.run([click], f"select tab {index}")
        return {"did": f"clicked the {clean(widget.tabText(index))!r} tab", "notes": []}

    def find_tab_widget(self, tab):
        candidates = []
        for window in self.interactive_windows():
            for widget in window.findChildren(QTabWidget):
                if widget.isVisible():
                    candidates.append(widget)
        for widget in reversed(candidates):
            try:
                self.tab_index(widget, tab)
                return widget
            except ActionError:
                continue
        raise ActionError(f"No visible tab matching {tab!r}.")

    @staticmethod
    def tab_index(widget, tab):
        texts = [normalise(widget.tabText(index)) for index in range(widget.count())]
        if isinstance(tab, int) or (isinstance(tab, str) and tab.strip().isdigit() and normalise(tab) not in texts
                                    and not any(text.startswith(normalise(tab) + " ") for text in texts)):
            index = int(tab)
            if 0 <= index < widget.count():
                return index
        wanted = normalise(str(tab))
        for matcher in (lambda text: text == wanted, lambda text: text.startswith(wanted), lambda text: wanted in text):
            for index, text in enumerate(texts):
                if matcher(text):
                    return index
        raise ActionError(f"No tab matching {tab!r}. Tabs: {', '.join(repr(clean(widget.tabText(i))) for i in range(widget.count()))}")

    def do_press_key(self, args):
        keys = str(args.get("keys") or args.get("key") or "").strip()
        if not keys:
            raise ActionError("Give keys such as 'Tab', 'Shift+Tab', 'Return', 'Escape', 'Ctrl+A' or 'F1'.")
        sequence = QKeySequence(keys)
        if sequence.isEmpty() or sequence.count() == 0:
            raise ActionError(f"Could not read {keys!r} as a key combination.")
        if args.get("ref") or args.get("name"):
            target = self.resolve(args)
            self.check_reachable(target)
        else:
            modal = QApplication.activeModalWidget()
            target = QApplication.focusWidget() or modal or QApplication.activeWindow()
            if target is None:
                windows = self.interactive_windows()
                if not windows:
                    raise ActionError("No window is open to receive the key press.")
                target = windows[-1]
            if modal is not None and target.window() is not modal and not modal.isAncestorOf(target.window()):
                target = modal.focusWidget() or modal
        combos = [sequence[index] for index in range(sequence.count())]
        description = self.describe(target)
        self.activate(target)
        handle = self.refs.handle(target)

        def press(combination):
            live = handle.get()
            if live is not None:
                QTest.keyClick(live, combination.key(), combination.keyboardModifiers())

        self.scheduler.run([lambda combination=combination: press(combination) for combination in combos],
                           f"press {keys}")
        return {"did": f"pressed {keys} in {description}", "notes": []}

    def do_draw(self, args):
        widget = self.resolve(args, roles=["canvas", "container"])
        notes = self.check_reachable(widget)
        strokes = args.get("strokes") or DEFAULT_SIGNATURE
        try:
            points = [[(float(x), float(y)) for x, y in stroke] for stroke in strokes]
        except (TypeError, ValueError):
            raise ActionError("strokes must be a list of strokes, each a list of [x, y] pairs from 0 to 1.")
        width, height = widget.width(), widget.height()
        handle = self.refs.handle(widget)
        steps = []
        for stroke in points:
            if not stroke:
                continue
            scaled = [QPoint(int(x * (width - 1)), int(y * (height - 1))) for x, y in stroke]
            steps.append(lambda first=scaled[0]: QTest.mousePress(handle.get(), LEFT, NO_MODIFIER, first))
            for point in scaled[1:]:
                steps.append(lambda point=point: QTest.mouseMove(handle.get(), point))
            steps.append(lambda last=scaled[-1]: QTest.mouseRelease(handle.get(), LEFT, NO_MODIFIER, last))
        self.activate(widget)
        self.scheduler.run(steps, f"draw on {self.describe(widget)}")
        return {"did": f"drew {len(points)} stroke(s) on {self.describe(widget)}", "notes": notes}

    def do_scroll(self, args):
        """Turn the mouse wheel with the pointer over the target, or drag a scroll bar to an end."""
        widget = self.resolve(args)
        self.check_reachable(widget, need_enabled=False)
        direction = (args.get("direction") or "down").lower()
        to = (args.get("to") or "").lower()
        horizontal = direction in ("left", "right")
        description = self.describe(widget)
        if to in ("top", "bottom", "start", "end"):
            area = widget
            while area is not None and not (isinstance(area, QAbstractScrollArea) and not isinstance(area, QComboBox)):
                area = area.parentWidget()
            if area is None:
                raise ActionError(f"{description} is not inside a scrollable area.")
            bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
            value = bar.minimum() if to in ("top", "start") else bar.maximum()
            handle = self.refs.handle(area)

            def drag():
                live = handle.get()
                (live.horizontalScrollBar() if horizontal else live.verticalScrollBar()).setValue(value)

            self.scheduler.run([drag], f"scroll {description}")
            return {"did": f"dragged the scroll bar of {self.describe(area)} to the {to}", "notes": []}
        notches = max(1, min(int(args.get("amount", 3) or 3), 50))
        sign = 1 if direction in ("up", "left") else -1
        delta = QPoint(sign * 120, 0) if horizontal else QPoint(0, sign * 120)
        handle = self.refs.handle(widget)

        def wheel():
            live = handle.get()
            if live is None:
                return
            surface = live.viewport() if isinstance(live, QAbstractScrollArea) and not isinstance(live, QComboBox) else live
            point = surface.rect().center()
            receiver = surface.childAt(point) or surface
            local = QPointF(receiver.mapFrom(surface, point))
            event = QWheelEvent(local, QPointF(surface.mapToGlobal(point)), QPoint(0, 0), delta,
                                Qt.MouseButton.NoButton, NO_MODIFIER, Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(receiver, event)

        self.scheduler.run([wheel] * notches, f"scroll {description}")
        return {"did": f"turned the mouse wheel {notches} notch(es) {direction} with the pointer over {description}",
                "notes": ["the wheel acts on whatever is under the pointer (a dropdown under the pointer changes "
                          "value), and otherwise scrolls the page, as with a real mouse"]}

    def do_set_value(self, args):
        widget = self.resolve(args, roles=["slider", "spinbox"])
        notes = self.check_reachable(widget)
        value = args.get("value")
        if not isinstance(widget, QAbstractSlider):
            raise ActionError(f"{self.describe(widget)} is not a slider; type into spin boxes instead.")
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ActionError("value must be a whole number")

        handle = self.refs.handle(widget)

        def drag():
            live = handle.get()
            live.setSliderDown(True)
            live.setValue(value)
            live.setSliderDown(False)

        self.scheduler.run([drag], f"drag {self.describe(widget)}")
        return {"did": f"dragged {self.describe(widget)} to {value}", "notes": notes}

    def do_close_window(self, args):
        if args.get("ref") or args.get("name"):
            window = self.resolve(args).window()
        else:
            window = QApplication.activeModalWidget() or QApplication.activeWindow()
        if window is None:
            raise ActionError("No window to close.")
        modal = QApplication.activeModalWidget()
        if modal is not None and window is not modal and not modal.isAncestorOf(window):
            raise ActionError(f"The modal dialog {modal.windowTitle()!r} must be closed first.")
        description = self.describe(window)
        handle = self.refs.handle(window)
        self.scheduler.run([lambda: handle.get().close() if handle.get() is not None else None], f"close {description}")
        return {"did": f"pressed the title-bar close button of {description}", "notes": []}

    def do_resize(self, args):
        window = None
        if args.get("ref") or args.get("name"):
            window = self.resolve(args).window()
        else:
            windows = [widget for widget in self.snapshotter.windows() if role_of(widget) == "window"]
            window = windows[0] if windows else None
        if window is None:
            raise ActionError("No main window to resize yet.")
        screen = QApplication.primaryScreen().availableGeometry()
        width = max(1, min(int(args.get("width", window.width())), screen.width()))
        height = max(1, min(int(args.get("height", window.height())), screen.height()))
        handle = self.refs.handle(window)
        self.scheduler.run([lambda: handle.get().resize(width, height)], "resize window")
        notes = []
        if int(args.get("width", width)) > screen.width() or int(args.get("height", height)) > screen.height():
            notes.append(f"clamped to the {screen.width()}x{screen.height()} screen; restart with a larger screen to go bigger")
        minimum = window.minimumSize()
        if width < minimum.width() or height < minimum.height():
            notes.append(f"the window's minimum size is {minimum.width()}x{minimum.height()}")
        return {"did": f"resized {self.describe(window)} to {width}x{height}", "notes": notes}


def type_characters(widget, text):
    """Type text key by key. Characters outside ASCII are sent as text-only key events."""
    for character in text:
        if character in "\n\r":
            QTest.keyClick(widget, Qt.Key.Key_Return)
        elif character == "\t":
            QTest.keyClick(widget, Qt.Key.Key_Tab)
        elif ord(character) < 128 and character.isprintable():
            QTest.keyClick(widget, character)  # PySide passes the char as a C char: ASCII only
        else:
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QApplication.sendEvent(widget, QKeyEvent(kind, Qt.Key.Key_unknown, NO_MODIFIER, character))


def read_text(widget):
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return widget.toPlainText()
    if isinstance(widget, QComboBox):
        return "\n".join([f"current: {widget.currentText()}"] +
                         [f"[{index}] {widget.itemText(index)}" for index in range(widget.count())])
    if isinstance(widget, QListWidget):
        return "\n".join(f"[{row}] {widget.item(row).text()}" for row in range(widget.count()))
    if isinstance(widget, QTreeWidget):
        lines = []

        def walk(item, depth):
            lines.append("  " * depth + " | ".join(item.text(c) for c in range(widget.columnCount()) if item.text(c)))
            for index in range(item.childCount()):
                walk(item.child(index), depth + 1)

        for index in range(widget.topLevelItemCount()):
            walk(widget.topLevelItem(index), 0)
        return "\n".join(lines)
    if hasattr(widget, "text") and callable(widget.text):
        return widget.text()
    if isinstance(widget, QDialog) or isinstance(widget, QWidget):
        return widget.windowTitle()
    return ""
