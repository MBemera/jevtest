"""Deterministic layout and accessibility heuristics for the visible windows.

These are prompts for investigation, not verdicts: each finding names the widget, what
was measured and why it might matter. Run them at several window sizes.
"""

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QApplication, QComboBox, QLabel, QLineEdit,
                               QPlainTextEdit, QScrollArea, QTextEdit, QWidget)

from .describe import INPUT_ROLES, LabelIndex, clean, name_of, role_of

MIN_TARGET = 24


def run(kind, snapshotter, refs):
    modal = QApplication.activeModalWidget()
    windows = [window for window in snapshotter.windows()
               if modal is None or window is modal or modal.isAncestorOf(window)]
    findings = []
    if kind in ("layout", "all"):
        for window in windows:
            findings.extend(layout_findings(window, snapshotter, refs))
    if kind in ("accessibility", "a11y", "all"):
        for window in windows:
            findings.extend(accessibility_findings(window, snapshotter, refs))
    focus_order = []
    if kind in ("accessibility", "a11y", "all", "focus") and windows:
        focus_order = tab_order(windows[-1], snapshotter, refs)
    return {"windows": [window.windowTitle() for window in windows], "findings": findings,
            "focus_order": focus_order}


def describe(snapshotter, widget):
    return snapshotter.describe(widget)


def layout_findings(window, snapshotter, refs):
    findings = []
    screen = QApplication.primaryScreen().availableGeometry()
    frame = window.frameGeometry()
    if not screen.contains(frame):
        findings.append({"check": "window-off-screen", "widget": describe(snapshotter, window),
                         "detail": f"window {frame.width()}x{frame.height()} at ({frame.x()},{frame.y()}) does not fit "
                                   f"the {screen.width()}x{screen.height()} screen"})
    minimum = window.minimumSize()
    if minimum.width() > screen.width() or minimum.height() > screen.height():
        findings.append({"check": "minimum-size-exceeds-screen", "widget": describe(snapshotter, window),
                         "detail": f"minimum size {minimum.width()}x{minimum.height()} is larger than the screen"})
    for area in window.findChildren(QScrollArea):
        if area.isVisible() and area.horizontalScrollBar().maximum() > 0:
            content = area.widget()
            findings.append({"check": "horizontal-scrolling", "widget": describe(snapshotter, area),
                             "detail": f"page content needs {content.minimumSizeHint().width() if content else '?'}px "
                                       f"but only {area.viewport().width()}px are visible, so the page scrolls sideways"})
    window_rect = QRect(0, 0, window.width(), window.height())
    labels = LabelIndex([window])
    for node in snapshotter.collect(window, labels):
        widget = node.widget
        if widget.visibleRegion().isEmpty():
            continue
        rect = QRect(widget.mapTo(window, widget.rect().topLeft()), widget.size())
        if not inside_scroll_area(widget) and not window_rect.contains(rect):
            findings.append({"check": "outside-window", "widget": describe(snapshotter, widget),
                             "detail": f"geometry {rect.x()},{rect.y()} {rect.width()}x{rect.height()} extends past the "
                                       f"{window.width()}x{window.height()} window"})
        if isinstance(widget, QAbstractButton) and clean(widget.text()):
            needed = widget.sizeHint().width()
            if needed - widget.width() > 6:
                findings.append({"check": "text-truncated", "widget": describe(snapshotter, widget),
                                 "detail": f"button text needs about {needed}px but the button is {widget.width()}px wide"})
        if isinstance(widget, QLabel) and clean(widget.text()):
            if widget.wordWrap():
                needed_height = widget.heightForWidth(widget.width())
                if needed_height - widget.height() > 4:
                    findings.append({"check": "text-clipped", "widget": describe(snapshotter, widget),
                                     "detail": f"wrapped text needs {needed_height}px of height but has {widget.height()}px"})
            elif widget.sizeHint().width() - widget.width() > 6:
                findings.append({"check": "text-clipped", "widget": describe(snapshotter, widget),
                                 "detail": f"text needs {widget.sizeHint().width()}px but the label is {widget.width()}px wide"})
        if isinstance(widget, QComboBox) and widget.count():
            longest = max(widget.fontMetrics().horizontalAdvance(widget.itemText(i)) for i in range(widget.count()))
            if widget.currentText() and widget.fontMetrics().horizontalAdvance(widget.currentText()) > widget.width() - 30:
                findings.append({"check": "value-truncated", "widget": describe(snapshotter, widget),
                                 "detail": f"the selected value is wider than the {widget.width()}px dropdown "
                                           f"(longest option {longest}px)"})
        if node.role in INPUT_ROLES and widget.isEnabled() and (widget.width() < MIN_TARGET or widget.height() < MIN_TARGET):
            findings.append({"check": "small-target", "widget": describe(snapshotter, widget),
                             "detail": f"{widget.width()}x{widget.height()}px is below the {MIN_TARGET}px minimum target size"})
    findings.extend(overlaps(window, snapshotter))
    return findings


def inside_scroll_area(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return True
        parent = parent.parentWidget()
    return False


def overlaps(window, snapshotter):
    findings = []
    leaves = [widget for widget in window.findChildren(QWidget)
              if widget.isVisible() and role_of(widget) in INPUT_ROLES and not widget.visibleRegion().isEmpty()]
    rects = [(widget, QRect(widget.mapTo(window, widget.rect().topLeft()), widget.size())) for widget in leaves]
    for index, (first, first_rect) in enumerate(rects):
        for second, second_rect in rects[index + 1:]:
            if first.isAncestorOf(second) or second.isAncestorOf(first):
                continue
            overlap = first_rect.intersected(second_rect)
            if overlap.isEmpty():
                continue
            smaller = min(first_rect.width() * first_rect.height(), second_rect.width() * second_rect.height()) or 1
            if overlap.width() * overlap.height() / smaller > 0.2:
                findings.append({"check": "overlap", "widget": describe(snapshotter, first),
                                 "detail": f"overlaps {describe(snapshotter, second)} by "
                                           f"{overlap.width()}x{overlap.height()}px"})
    return findings[:20]


def accessibility_findings(window, snapshotter, refs):
    findings = []
    labels = LabelIndex([window])
    for node in snapshotter.collect(window, labels):
        widget = node.widget
        if node.role not in INPUT_ROLES:
            continue
        if not name_of(widget, labels, node.role, strict=True) and node.role not in ("tabs",):
            findings.append({"check": "unlabelled-control", "widget": describe(snapshotter, widget),
                             "detail": "no visible label, accessible name, placeholder or tooltip names this control; "
                                       "a screen reader announces it without a name"})
        if widget.isEnabled() and widget.focusPolicy() == Qt.FocusPolicy.NoFocus and node.role != "canvas":
            findings.append({"check": "not-keyboard-reachable", "widget": describe(snapshotter, widget),
                             "detail": "focus policy is NoFocus, so Tab never reaches it"})
        if isinstance(widget, (QLineEdit,)) and not labels.names.get(id(widget)) and widget.placeholderText() \
                and not widget.accessibleName():
            findings.append({"check": "placeholder-as-label", "widget": describe(snapshotter, widget),
                             "detail": "only placeholder text names this field; it disappears once the user types"})
        if isinstance(widget, (QTextEdit, QPlainTextEdit)) and widget.tabChangesFocus() is False and widget.isEnabled() \
                and not widget.isReadOnly():
            findings.append({"check": "tab-trap", "widget": describe(snapshotter, widget),
                             "detail": "Tab inserts a tab character here instead of moving focus (Ctrl+Tab leaves)"})
    return findings


def tab_order(window, snapshotter, refs, limit=60):
    order = []
    start = window.focusWidget() or window
    widget = start.nextInFocusChain()
    seen = set()
    labels = LabelIndex([window])
    while widget is not None and id(widget) not in seen and len(order) < limit:
        seen.add(id(widget))
        if widget.isVisible() and widget.isEnabled() and widget.focusPolicy() & Qt.FocusPolicy.TabFocus \
                and widget.window() is window:
            order.append(f"[{refs.of(widget)}] {role_of(widget)} {name_of(widget, labels)!r}")
        widget = widget.nextInFocusChain()
        if widget is start:
            break
    return order
