"""Window mode: let a person watch a run, and keep their own input from disturbing it.

When DT's windows are on the real screen, each action is announced before it happens: a frame is
drawn around the control Jev is about to use, with a caption such as "Step 12: Click 'Save
preparation'", and the run pauses briefly (the pace) so the eye can follow. The frame is a child
of DT's own window that ignores the mouse, so it cannot change what DT does, and snapshots and
screenshots leave it out.

The input guard ignores the laptop's real mouse and keyboard on DT's windows while Jev is driving
(unless --allow-input). Real input always reaches a QWindow first; Jev's own input is sent straight
to widgets, so the guard can tell them apart. Keyboard shortcuts are resolved before the window sees
the key, so they are blocked unless Jev is injecting input at that moment. Closing a window is not
blocked: Qt reports DT's own close() calls exactly like a click on the title-bar button, so closing
DT's window during a run ends that app, as it would for a person.
"""

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QWindow
from PySide6.QtWidgets import QApplication, QWidget

FRAME = QColor(236, 64, 122)
CAPTION_BACKGROUND = QColor(28, 28, 32, 235)
REAL_INPUT = frozenset({
    QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
    QEvent.Type.MouseMove, QEvent.Type.Wheel, QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
    QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd, QEvent.Type.TabletPress,
    QEvent.Type.TabletMove, QEvent.Type.TabletRelease,
})
SHORTCUTS = frozenset({QEvent.Type.Shortcut, QEvent.Type.ShortcutOverride})


class Spotlight(QWidget):
    """A frame and caption over one DT window; transparent to the mouse, never focused."""

    def __init__(self, window):
        super().__init__(window)
        self.setProperty("jev_overlay", True)
        self.setObjectName("jev-spotlight")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self.target = QRect()
        self.caption = ""

    def point_at(self, widget, caption):
        """Frame a widget, or with no widget show the caption alone at the top of the window."""
        window = self.parentWidget()
        self.setGeometry(window.rect())
        if widget is not None:
            self.target = QRect(widget.mapTo(window, QPoint(0, 0)), widget.size()).adjusted(-3, -3, 3, 3)
        else:
            self.target = QRect()
        self.caption = caption
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.target.isNull():
            painter.setPen(QPen(FRAME, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.target, 5, 5)
        if not self.caption:
            return
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(9.5, font.pointSizeF()))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text = metrics.elidedText(self.caption, Qt.TextElideMode.ElideRight, max(160, self.width() - 24))
        box = QRect(0, 0, metrics.horizontalAdvance(text) + 18, metrics.height() + 10)
        if self.target.isNull():
            box.moveTo(max(6, (self.width() - box.width()) // 2), 6)
        else:
            x = min(max(6, self.target.left()), max(6, self.width() - box.width() - 6))
            y = self.target.top() - box.height() - 6
            if y < 6:
                y = min(self.target.bottom() + 6, max(6, self.height() - box.height() - 6))
            box.moveTo(x, y)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CAPTION_BACKGROUND)
        painter.drawRoundedRect(box, 5, 5)
        painter.setPen(QColor("white"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class Watch:
    """Announces each action on screen and paces the run (GUI-thread methods unless noted)."""

    def __init__(self, pace=0.5, label=""):
        self.pace = max(0.0, float(pace or 0))
        self.label = label
        self.spotlights = {}
        self.generation = 0
        self.caption = ""

    def showing(self):
        return any(shiboken6.isValid(spot) and spot.isVisible() for spot in self.spotlights.values())

    def spotlight(self, window):
        spot = self.spotlights.get(id(window))
        if spot is None or not shiboken6.isValid(spot) or spot.parentWidget() is not window:
            spot = Spotlight(window)
            self.spotlights[id(window)] = spot
        return spot

    def show(self, widget, caption, window=None):
        """Frame the widget with the caption; with only a window, show the caption at its top."""
        self.hide_all()
        self.generation += 1
        self.caption = caption
        if widget is not None and shiboken6.isValid(widget) and widget.isVisible():
            self.spotlight(widget.window()).point_at(widget, caption)
        elif window is not None and shiboken6.isValid(window) and window.isVisible():
            self.spotlight(window).point_at(None, caption)

    def hide_all(self):
        for key, spot in list(self.spotlights.items()):
            if shiboken6.isValid(spot):
                spot.hide()
            else:
                del self.spotlights[key]

    def fade_later(self, delay_ms=4000):
        generation = self.generation
        QTimer.singleShot(delay_ms, lambda: generation == self.generation and self.hide_all())

    def hidden_for_capture(self):
        """Screenshots show DT only: hide the frames while grabbing, then put them back."""
        watch = self

        class Hidden:
            def __enter__(self):
                self.visible = [spot for spot in watch.spotlights.values()
                                if shiboken6.isValid(spot) and spot.isVisible()]
                for spot in self.visible:
                    spot.hide()

            def __exit__(self, *exc):
                for spot in self.visible:
                    if shiboken6.isValid(spot):
                        spot.show()
                return False

        return Hidden()


class InputGuard(QObject):
    """Ignores the real mouse and keyboard on DT's windows while Jev drives them."""

    def __init__(self, scheduler, log):
        super().__init__()
        self.scheduler = scheduler
        self.log = log
        self.ignored = 0

    def eventFilter(self, watched, event):  # noqa: N802 - Qt naming
        kind = event.type()
        if kind in REAL_INPUT:
            # Only the window system delivers spontaneous input to a QWindow; Jev's input goes to widgets.
            if not event.spontaneous() or not isinstance(watched, QWindow):
                return False
            return self.ignore(kind)
        if kind in SHORTCUTS and not self.scheduler.injecting:
            return self.ignore(kind)
        return False

    def ignore(self, kind):
        self.ignored += 1
        if self.ignored == 1:
            self.log.emit("harness_note", note="Your own mouse and keyboard are ignored in DT's windows while Jev "
                                               "drives them (window mode). Start with --allow-input to take over.")
        return True


def install_input_guard(scheduler, log):
    guard = InputGuard(scheduler, log)
    QApplication.instance().installEventFilter(guard)
    return guard
