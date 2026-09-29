"""Turn the live Qt widget tree into a compact, stable text snapshot.

Every widget that appears in a snapshot gets a reference such as ``w12``. The reference
is stored on the widget as a dynamic property, so it stays the same for as long as the
widget exists, across snapshots and across dialogs opening and closing.
"""

import weakref

import shiboken6
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFormLayout,
    QGridLayout, QGroupBox, QLabel, QLineEdit, QListView, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QScrollArea, QScrollBar, QSplitter,
    QStackedWidget, QStatusBar, QTabBar, QTableView, QTabWidget, QTextBrowser, QTextEdit,
    QTreeView, QTreeWidget, QWidget,
)

REF_PROPERTY = "jev_ref"
# Shiboken invalidates child wrappers when the wrapper of a C++-owned window (for example a
# QMessageBox from a static helper) is garbage collected, even though the widgets still
# exist. Holding the top-level wrappers keeps every child wrapper usable while it lives.
PINNED = {}
TEXT_ROLES = {"textbox", "textarea"}
INPUT_ROLES = {"button", "checkbox", "radio", "combobox", "textbox", "textarea", "list", "tree",
               "table", "spinbox", "slider", "tabs", "canvas", "document"}
MESSAGE_ICONS = {
    QMessageBox.Icon.Information: "information",
    QMessageBox.Icon.Warning: "warning",
    QMessageBox.Icon.Critical: "critical",
    QMessageBox.Icon.Question: "question",
}


class Refs:
    def __init__(self):
        self.counter = 0
        self.by_ref = {}

    def of(self, widget):
        value = widget.property(REF_PROPERTY)
        if value:
            return value
        self.counter += 1
        value = f"w{self.counter}"
        widget.setProperty(REF_PROPERTY, value)
        try:
            self.by_ref[value] = weakref.ref(widget)
        except TypeError:
            pass
        return value

    def handle(self, widget):
        return Handle(self, widget)

    def find(self, ref):
        ref = str(ref).strip().lstrip("[").rstrip("]")
        holder = self.by_ref.get(ref)
        widget = holder() if holder else None
        if widget is not None and shiboken6.isValid(widget):
            return widget
        for candidate in QApplication.allWidgets():
            if candidate.property(REF_PROPERTY) == ref:
                return candidate
        return None


class Handle:
    """A widget reference that survives wrapper invalidation by re-finding the widget by ref."""

    def __init__(self, refs, widget):
        self.refs = refs
        self.ref = refs.of(widget)
        self.widget = widget
        pin(widget.window())

    def get(self):
        if self.widget is not None and shiboken6.isValid(self.widget):
            return self.widget
        self.widget = self.refs.find(self.ref)
        return self.widget


def pin(window):
    if window is None or not window.isVisible():
        return
    for key, held in list(PINNED.items()):
        if not shiboken6.isValid(held):
            del PINNED[key]
    PINNED[id(window)] = window


def unpin(window):
    PINNED.pop(id(window), None)


def clean(text):
    return " ".join(str(text or "").replace("&&", "\0").replace("&", "").replace("\0", "&").split())


def one_line(text, limit=160):
    text = " / ".join(part.strip() for part in str(text or "").splitlines() if part.strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def quoted(text, limit=160):
    return '"' + one_line(text, limit).replace('"', "'") + '"'


def is_popup(widget):
    return bool(widget.windowFlags() & Qt.WindowType.Popup) and (widget.windowFlags() & Qt.WindowType.Popup) == Qt.WindowType.Popup


def role_of(widget):
    if isinstance(widget, QMessageBox):
        return "message box"
    if isinstance(widget, QDialog):
        return "dialog"
    if isinstance(widget, QMainWindow):
        return "window"
    if isinstance(widget, QDockWidget):
        return "dock"
    if isinstance(widget, QTabWidget):
        return "tabs"
    if isinstance(widget, QGroupBox):
        return "group"
    if isinstance(widget, QCheckBox):
        return "checkbox"
    if isinstance(widget, QRadioButton):
        return "radio"
    if isinstance(widget, QAbstractButton):
        return "button"
    if isinstance(widget, QComboBox):
        return "combobox"
    if isinstance(widget, QLineEdit):
        return "textbox"
    if isinstance(widget, QTextBrowser):
        return "document"
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return "textarea"
    if isinstance(widget, QTreeView):
        return "tree"
    if isinstance(widget, QTableView):
        return "table"
    if isinstance(widget, QListView):
        return "list"
    if isinstance(widget, QAbstractSpinBox):
        return "spinbox"
    if isinstance(widget, QScrollBar):
        return "scrollbar"
    if isinstance(widget, QAbstractSlider):
        return "slider"
    if isinstance(widget, QProgressBar):
        return "progress"
    if isinstance(widget, QLabel):
        return "text"
    if isinstance(widget, QStatusBar):
        return "statusbar"
    if isinstance(widget, QMenu):
        return "menu"
    if isinstance(widget, QTabBar):
        return "tabbar"
    if isinstance(widget, QAbstractScrollArea):
        return "scroll"
    if type(widget).__name__ == "QVideoWidget":
        return "video"
    if type(widget).__module__ not in ("PySide6.QtWidgets",) and type(widget).__name__ != "QWidget" \
            and not widget.findChildren(QWidget):
        return "canvas"  # a custom-painted leaf such as the signature pad
    return "container"


class LabelIndex:
    """Which visible label names which input, collected once per snapshot."""

    def __init__(self, windows):
        self.names = {}
        self.consumed = set()
        for window in windows:
            for form in window.findChildren(QFormLayout):
                for row in range(form.rowCount()):
                    label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                    field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                    label_widget = label.widget() if label else None
                    field_widget = first_widget(field) if field else None
                    if isinstance(label_widget, QLabel) and field_widget is not None:
                        self.names[id(field_widget)] = clean(label_widget.text())
                        self.consumed.add(id(label_widget))
            for label in window.findChildren(QLabel):
                buddy = label.buddy()
                if buddy is not None and id(buddy) not in self.names:
                    self.names[id(buddy)] = clean(label.text())
                    self.consumed.add(id(label))


def first_widget(item):
    if item is None:
        return None
    if item.widget() is not None:
        return item.widget()
    layout = item.layout()
    if layout is not None:
        for index in range(layout.count()):
            found = first_widget(layout.itemAt(index))
            if found is not None:
                return found
    return None


def preceding_label(widget):
    """A short QLabel placed immediately before the widget in its layout usually names it."""
    parent = widget.parentWidget()
    if parent is None or parent.layout() is None:
        return None
    layout = find_layout_containing(parent.layout(), widget)
    if layout is None:
        return None
    index = layout.indexOf(widget)
    if index <= 0:
        return None
    before = layout.itemAt(index - 1)
    candidate = before.widget() if before else None
    if isinstance(candidate, QLabel) and candidate.isVisible():
        text = clean(candidate.text())
        if text and len(text) <= 80:
            return candidate
    return None


def find_layout_containing(layout, widget):
    if layout.indexOf(widget) >= 0:
        return layout
    for index in range(layout.count()):
        child = layout.itemAt(index).layout()
        if child is not None:
            found = find_layout_containing(child, widget)
            if found is not None:
                return found
    return None


def name_of(widget, labels, role=None, strict=False):
    """The name a person would use for the control. strict=True ignores group-box titles,
    which Qt does not expose to screen readers as the control's accessible name."""
    role = role or role_of(widget)
    if role in ("button", "checkbox", "radio"):
        text = clean(widget.text())
        if text:
            return text
    if widget.accessibleName():
        return clean(widget.accessibleName())
    if id(widget) in labels.names:
        return labels.names[id(widget)]
    if role == "group":
        return clean(widget.title())
    if role == "dock":
        return clean(widget.windowTitle())
    if isinstance(widget, QComboBox) and widget.isEditable() and widget.lineEdit().placeholderText():
        placeholder = clean(widget.lineEdit().placeholderText())
    elif isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)) and widget.placeholderText():
        placeholder = clean(widget.placeholderText())
    else:
        placeholder = ""
    label = preceding_label(widget) if role in INPUT_ROLES else None
    if label is not None:
        labels.consumed.add(id(label))
        return clean(label.text())
    if placeholder:
        return placeholder
    if widget.toolTip():
        return clean(widget.toolTip())
    if widget.isWindow() and widget.windowTitle():
        return clean(widget.windowTitle())
    name = widget.objectName()
    if name and not name.startswith("qt_"):
        return name
    if not strict and role in INPUT_ROLES:
        parent = widget.parentWidget()
        while parent is not None and not parent.isWindow():
            if isinstance(parent, QGroupBox) and clean(parent.title()):
                return clean(parent.title())
            parent = parent.parentWidget()
    return ""


def ordered_children(widget):
    """Direct child widgets in reading order: layout order when there is one, else geometry."""
    children = [child for child in widget.children() if isinstance(child, QWidget) and not child.isWindow()]
    if isinstance(widget, QSplitter):
        return [widget.widget(index) for index in range(widget.count())]
    layout = widget.layout()
    ordered = []
    if layout is not None and not isinstance(widget, QMainWindow):
        seen = set()
        for child in layout_widgets(layout):
            if child in children and id(child) not in seen:
                seen.add(id(child))
                ordered.append(child)
        rest = [child for child in children if id(child) not in seen]
    else:
        rest = children
    rest.sort(key=lambda child: (child.geometry().y() // 12, child.geometry().x()))
    return ordered + rest


def layout_widgets(layout):
    items = []
    if isinstance(layout, QGridLayout):
        entries = []
        for index in range(layout.count()):
            row, column, _, _ = layout.getItemPosition(index)
            entries.append(((row, column), layout.itemAt(index)))
        sequence = [item for _, item in sorted(entries, key=lambda entry: entry[0])]
    elif isinstance(layout, QFormLayout):
        sequence = []
        for row in range(layout.rowCount()):
            for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole,
                         QFormLayout.ItemRole.SpanningRole):
                item = layout.itemAt(row, role)
                if item is not None:
                    sequence.append(item)
    else:
        sequence = [layout.itemAt(index) for index in range(layout.count())]
    for item in sequence:
        if item is None:
            continue
        if item.widget() is not None:
            items.append(item.widget())
        elif item.layout() is not None:
            items.extend(layout_widgets(item.layout()))
    return items


class Node:
    __slots__ = ("widget", "role", "depth", "name", "ref", "extra")

    def __init__(self, widget, role, depth):
        self.widget, self.role, self.depth = widget, role, depth
        self.name, self.ref, self.extra = "", "", []


class Snapshotter:
    def __init__(self, refs, max_items=8, text_limit=160):
        self.refs = refs
        self.max_items = max_items
        self.text_limit = text_limit

    # ----- windows -------------------------------------------------------------------
    @staticmethod
    def windows():
        tops = [widget for widget in QApplication.topLevelWidgets()
                if widget.isVisible() and not is_popup(widget) and not widget.property("jev_overlay")]
        for widget in tops:
            pin(widget)
        order = {"window": 0, "dock": 1, "dialog": 2, "message box": 3}
        modal = QApplication.activeModalWidget()

        def key(widget):
            return (widget is modal, order.get(role_of(widget), 1), tops.index(widget))

        return sorted(tops, key=key)

    def collect(self, window, labels, full=False):
        nodes = []
        self.walk_children(window, 1, nodes, full)
        for node in nodes:
            node.name = name_of(node.widget, labels, node.role)
        return [node for node in nodes if not (node.role == "text" and id(node.widget) in labels.consumed)]

    def walk_children(self, widget, depth, nodes, full):
        if isinstance(widget, QMainWindow):
            children = [child for child in (widget.menuWidget(), widget.centralWidget()) if child is not None]
            children += sorted(widget.findChildren(QDockWidget, options=Qt.FindChildOption.FindDirectChildrenOnly),
                               key=lambda dock: dock.geometry().x())
        elif isinstance(widget, QScrollArea):
            children = [widget.widget()] if widget.widget() is not None else []
        elif isinstance(widget, QDockWidget):
            children = [widget.widget()] if widget.widget() is not None else []
        elif isinstance(widget, (QTabWidget,)):
            children = [widget.currentWidget()] if widget.currentWidget() is not None else []
        elif isinstance(widget, QStackedWidget):
            children = [widget.currentWidget()] if widget.currentWidget() is not None else []
        else:
            children = ordered_children(widget)
        for child in children:
            if child is None or not child.isVisible():
                continue
            self.visit(child, depth, nodes, full)

    def visit(self, widget, depth, nodes, full):
        role = role_of(widget)
        if role in ("scrollbar", "statusbar", "menu") or (role == "tabbar" and isinstance(widget.parent(), QTabWidget)):
            return
        if isinstance(widget, QDialogButtonBox) or role == "container":
            self.walk_children(widget, depth, nodes, full)
            return
        if role == "scroll" and isinstance(widget, QScrollArea):
            vertical, horizontal = widget.verticalScrollBar(), widget.horizontalScrollBar()
            if vertical.maximum() > 0 or horizontal.maximum() > 0:
                node = Node(widget, "scroll area", depth)
                node.extra.append(scroll_state(vertical, horizontal))
                nodes.append(node)
                self.walk_children(widget, depth + 1, nodes, full)
            else:
                self.walk_children(widget, depth, nodes, full)
            return
        if role == "scroll":
            self.walk_children(widget, depth, nodes, full)
            return
        if role == "text" and not clean(widget.text()) and not widget.accessibleName():
            return  # empty labels and bare icons carry nothing a tester can act on
        node = Node(widget, role, depth)
        nodes.append(node)
        if role in ("group", "tabs", "dock"):
            self.walk_children(widget, depth + 1, nodes, full)

    # ----- rendering -----------------------------------------------------------------
    def render_window(self, window, labels, *, modal, full, lines):
        role = role_of(window)
        ref = self.refs.of(window)
        flags = []
        if window is modal:
            flags.append("modal, has focus")
        elif modal is not None and not modal.isAncestorOf(window):
            flags.append("blocked by the modal dialog")
        elif window.isActiveWindow():
            flags.append("active")
        size = f"{window.width()}x{window.height()}"
        header = f"[{ref}] {role} {quoted(window.windowTitle())} {size}"
        if isinstance(window, QMessageBox):
            header = f"[{ref}] message box ({MESSAGE_ICONS.get(window.icon(), 'plain')}) {quoted(window.windowTitle())}"
        lines.append(header + (f" ({', '.join(flags)})" if flags else ""))
        if modal is not None and window is not modal and not modal.isAncestorOf(window) and not full:
            lines.append("  … contents hidden while a modal dialog is open (use snapshot full=true to include them)")
            return []
        nodes = self.collect(window, labels, full)
        for node in nodes:
            lines.append(self.render_node(node))
        return nodes

    def render_node(self, node):
        widget, role = node.widget, node.role
        node.ref = self.refs.of(widget)
        indent = "  " * node.depth
        parts = [f"{indent}[{node.ref}] {role}"]
        if node.name and role not in ("text",):
            parts.append(quoted(node.name, 120))
        detail = self.describe_value(widget, role, node)
        if detail:
            parts.append(detail)
        states = self.states(widget, role, node)
        line = " ".join(parts)
        if states:
            line += " (" + ", ".join(states) + ")"
        extra = [text for text in node.extra if text]
        if extra and role != "scroll area":
            line += "\n" + "\n".join(f"{indent}    {text}" for text in extra)
        elif extra:
            line += " " + " ".join(extra)
        return line

    def describe_value(self, widget, role, node):
        if role == "text":
            return quoted(widget.text(), self.text_limit * 2)
        if role == "textbox":
            if widget.echoMode() != QLineEdit.EchoMode.Normal:
                if not widget.text():
                    return "= (empty, input hidden)"
                return f"= {'•' * min(len(widget.text()), 12)} ({len(widget.text())} characters, input hidden)"
            text = f"= {quoted(widget.text(), self.text_limit)}"
            if not widget.text() and widget.placeholderText() and clean(widget.placeholderText()) != node.name:
                text += f" placeholder {quoted(widget.placeholderText(), 80)}"
            return text
        if role in ("textarea", "document"):
            value = widget.toPlainText()
            text = f"= {quoted(value, self.text_limit)}"
            if len(value) > self.text_limit:
                text += f" ({len(value)} characters; read_text for all)"
            if not value and widget.placeholderText() and clean(widget.placeholderText()) != node.name:
                text += f" placeholder {quoted(widget.placeholderText(), 80)}"
            return text
        if role in ("checkbox", "radio"):
            return "[x]" if widget.isChecked() else "[ ]"
        if role == "combobox":
            return self.combo_value(widget)
        if role in ("list", "tree", "table"):
            count, rendered = self.items(widget, role)
            node.extra.extend(rendered)
            return f"({count})"
        if role == "tabs":
            names = []
            for index in range(widget.count()):
                label = clean(widget.tabText(index))
                if index == widget.currentIndex():
                    label = f"*{label}*"
                if not widget.isTabEnabled(index):
                    label += " (disabled)"
                names.append(label)
            return "tabs: " + " | ".join(names)
        if role in ("slider", "spinbox"):
            if isinstance(widget, QAbstractSpinBox):
                return f"= {quoted(widget.text(), 40)}"
            return f"= {widget.value()} (range {widget.minimum()}..{widget.maximum()})"
        if role == "progress":
            return f"= {widget.value()}/{widget.maximum()}"
        if role in ("canvas", "video"):
            return f"{type(widget).__name__} {widget.width()}x{widget.height()}"
        return ""

    def combo_value(self, combo):
        options = [clean(combo.itemText(index)) for index in range(combo.count())]
        shown = [option if option else "(blank)" for option in options]
        if len(shown) > self.max_items:
            listed = ", ".join(shown[: self.max_items]) + f", … +{len(shown) - self.max_items} more"
        else:
            listed = ", ".join(shown)
        text = f"= {quoted(combo.currentText(), 80)}"
        if combo.isEditable():
            text += " editable"
            if not combo.currentText() and combo.lineEdit().placeholderText():
                text += f" placeholder {quoted(combo.lineEdit().placeholderText(), 80)}"
        return text + f" options: [{listed}]" if options else text + " options: []"

    def items(self, view, role):
        if isinstance(view, QTreeWidget):
            return self.tree_items(view)
        model = view.model()
        if model is None:
            return "0 items", []
        rows = model.rowCount(view.rootIndex() if isinstance(view, QAbstractItemView) else QModelIndex())
        current = view.currentIndex().row() if view.currentIndex().isValid() else -1
        hidden = [row for row in range(rows) if isinstance(view, QListView) and view.isRowHidden(row)]
        visible = [row for row in range(rows) if row not in set(hidden)]
        shown = visible[: self.max_items]
        if current in visible and current not in shown:
            shown.append(current)
        lines = []
        selection = view.selectionModel()
        for row in shown:
            index = model.index(row, 0, view.rootIndex())
            text = one_line(index.data(Qt.ItemDataRole.DisplayRole), self.text_limit)
            marks = []
            check = index.data(Qt.ItemDataRole.CheckStateRole)
            if check is not None:
                marks.append("[x]" if Qt.CheckState(check) == Qt.CheckState.Checked else "[ ]")
            if row == current or (selection is not None and selection.isSelected(index)):
                marks.append("*selected*")
            if not (model.flags(index) & Qt.ItemFlag.ItemIsEnabled):
                marks.append("(disabled)")
            lines.append(f"- [{row}] {' '.join(marks) + ' ' if marks else ''}{quoted(text, self.text_limit)}")
        more = len(visible) - len(shown)
        if more > 0:
            lines.append(f"- … {more} more (use list_items)")
        count = f"{len(visible)} item{'s' if len(visible) != 1 else ''}"
        if hidden:
            count += f", {len(hidden)} hidden by filter"
        if current >= 0:
            count += f", selected row {current}"
        return count, lines

    def tree_items(self, tree):
        lines, total = [], [0]
        current = tree.currentItem()

        def visit(item, depth, path):
            total[0] += 1
            if len(lines) >= self.max_items * 2:
                return
            columns = [clean(item.text(column)) for column in range(tree.columnCount()) if clean(item.text(column))]
            label = " | ".join(columns)
            marks = "*selected* " if item is current else ""
            lines.append(f"{'  ' * depth}- {marks}{quoted(label, self.text_limit)}")
            if item.isExpanded():
                for index in range(item.childCount()):
                    visit(item.child(index), depth + 1, path)
            elif item.childCount():
                lines[-1] += f" (collapsed, {item.childCount()} children)"

        for index in range(tree.topLevelItemCount()):
            visit(tree.topLevelItem(index), 0, [])
        if total[0] > len(lines):
            lines.append(f"- … more items (use list_items)")
        return f"{total[0]} items", lines

    def states(self, widget, role, node):
        states = []
        if not widget.isEnabled():
            states.append("disabled")
        if role in TEXT_ROLES and getattr(widget, "isReadOnly", lambda: False)():
            states.append("read-only")
        if role == "button":
            if widget.isCheckable():
                states.append("pressed" if widget.isChecked() else "not pressed")
            if isinstance(widget, QPushButton) and widget.isDefault() and widget.isEnabled():
                states.append("default")
        if QApplication.focusWidget() is widget or (
                isinstance(widget, QComboBox) and widget.isEditable() and QApplication.focusWidget() is widget.lineEdit()):
            states.append("focused")
        if widget.visibleRegion().isEmpty() and widget.width() > 0:
            states.append("scrolled out of view")
        tip = clean(widget.toolTip())
        if tip and tip != node.name:
            states.append(f"tooltip {quoted(tip, 100)}")
        return states

    # ----- whole screen --------------------------------------------------------------
    def snapshot(self, *, full=False, app_state=None):
        windows = self.windows()
        labels = LabelIndex(windows)
        modal = QApplication.activeModalWidget()
        lines, nodes = [], []
        screen = QApplication.primaryScreen().size()
        lines.append(f"Screen {screen.width()}x{screen.height()} | {len(windows)} open window(s)")
        focus = QApplication.focusWidget()
        if modal is not None:
            lines.append(f"Modal dialog open: [{self.refs.of(modal)}] {quoted(modal.windowTitle())}. "
                         "Only it accepts input until it closes.")
        for key, value in (app_state or {}).items():
            if value not in (None, "", False):
                lines.append(f"{key}: {value}")
        lines.append("")
        for window in windows:
            nodes.extend(self.render_window(window, labels, modal=modal, full=full, lines=lines))
            lines.append("")
        popup = QApplication.activePopupWidget()
        if popup is not None:
            lines.append(f"Open popup: [{self.refs.of(popup)}] {type(popup).__name__}")
            for view in popup.findChildren(QListView):
                if view.isVisible():
                    count, rendered = self.items(view, "list")
                    lines.append(f"  popup list ({count})")
                    lines.extend("    " + line for line in rendered)
        if focus is not None:
            lines.append(f"Keyboard focus: [{self.refs.of(focus)}] {role_of(focus)} "
                         f"{quoted(name_of(focus, labels), 80)}")
        summary = [{"ref": node.ref, "role": node.role, "name": node.name, "depth": node.depth,
                    "enabled": node.widget.isEnabled()} for node in nodes]
        return "\n".join(lines).rstrip() + "\n", summary

    def describe(self, widget, labels=None):
        """One line naming a widget, for action results and errors."""
        labels = labels or LabelIndex([widget.window()])
        role = role_of(widget)
        name = name_of(widget, labels, role)
        text = f"[{self.refs.of(widget)}] {role}"
        if role == "text":
            return text + " " + quoted(widget.text(), 80)
        return text + (" " + quoted(name, 80) if name else "")


def scroll_state(vertical, horizontal):
    parts = []
    if vertical.maximum() > 0:
        percent = round(100 * vertical.value() / vertical.maximum())
        where = "top" if vertical.value() == 0 else "bottom" if vertical.value() >= vertical.maximum() else f"{percent}% down"
        parts.append(f"scrollable vertically, at {where}")
    if horizontal.maximum() > 0:
        parts.append("scrollable horizontally (content wider than the view)")
    return "(" + "; ".join(parts) + ")"


def window_title_path(widget):
    window = widget.window()
    return window.windowTitle() if window is not None else ""
