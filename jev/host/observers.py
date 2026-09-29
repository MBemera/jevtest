"""Qt-side observers: Qt log messages, dialogs opening and closing, status bar text."""

import re
import sys

from PySide6.QtCore import QEvent, QObject, QtMsgType, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox

from .describe import unpin
from .monitor import clip, raw_error_reason

# Messages the offscreen platform and headless multimedia print on every run. They say
# nothing about the app under test, so they stay in host.log and out of the event log.
QT_NOISE = [re.compile(pattern) for pattern in (
    r"This plugin does not support",
    r"pipewire",
    r"PulseAudioService",
    r"pa_context_connect",
    r"Using Qt multimedia with FFmpeg",
    r"qt\.multimedia\.symbolsresolver",
    r"QFont::fromString",
    r"Fontconfig",
    r"propagateSizeHints",
    r"QStandardPaths: XDG_RUNTIME_DIR",
    r"runtime directory '.*' is not owned",
    # Headless machines have no sound card or GPU; these describe the test machine, not DT.
    r"No audio device detected",
    r"No RHI backend",
    r"QRhi",
    r"[Ff]ailed to (create|initialize) (RHI|OpenGL|EGL|VA-API|VDPAU)",
    r"libva|vaapi|VDPAU|va_openDriver",
    r"qt\.multimedia\.(ffmpeg|audio|pulseaudio)",
    r"PipeWire|GStreamer",
)]

LEVELS = {
    QtMsgType.QtDebugMsg: "debug",
    QtMsgType.QtInfoMsg: "info",
    QtMsgType.QtWarningMsg: "warning",
    QtMsgType.QtCriticalMsg: "critical",
    QtMsgType.QtFatalMsg: "fatal",
}

MESSAGE_ICONS = {
    QMessageBox.Icon.NoIcon: "plain",
    QMessageBox.Icon.Information: "information",
    QMessageBox.Icon.Warning: "warning",
    QMessageBox.Icon.Critical: "critical",
    QMessageBox.Icon.Question: "question",
}


def install_qt_message_handler(log):
    def handler(mode, context, message):
        level = LEVELS.get(mode, "unknown")
        category = getattr(context, "category", "") or ""
        line = f"[qt {level}] {category + ': ' if category and category != 'default' else ''}{message}"
        try:
            sys.__stderr__.write(line + "\n")
        except (OSError, ValueError, AttributeError):
            pass
        if level in ("debug", "info"):
            return
        if any(pattern.search(message) or pattern.search(category) for pattern in QT_NOISE):
            return
        log.emit("qt_message", level=level, category=category, message=clip(message, 1000))

    qInstallMessageHandler(handler)


def button_texts(box):
    return [button.text().replace("&", "") for button in box.buttons()]


def describe_dialog(widget):
    info = {"title": widget.windowTitle(), "class": type(widget).__name__,
            "modal": bool(widget.isModal()) if isinstance(widget, QDialog) else False}
    if isinstance(widget, QMessageBox):
        info.update(icon=MESSAGE_ICONS.get(widget.icon(), "other"), message=clip(widget.text(), 2000),
                    informative=clip(widget.informativeText(), 1000), buttons=button_texts(widget))
    return info


class WindowObserver(QObject):
    """Application event filter recording dialogs and wiring status bar observation."""

    def __init__(self, log, on_main_window=None):
        super().__init__()
        self.log = log
        self.on_main_window = on_main_window
        self.watched_status_bars = set()
        self.open_dialogs = {}
        self.last_closed_dialog = None
        self.main_window = None

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.Show, QEvent.Type.Hide):
            try:
                if watched.isWidgetType() and watched.isWindow():
                    if kind == QEvent.Type.Show:
                        self.window_shown(watched)
                    else:
                        self.window_hidden(watched)
            except RuntimeError:
                pass  # the C++ object is already being destroyed
        return False

    def window_shown(self, widget):
        if isinstance(widget, QMainWindow):
            if self.main_window is not widget:
                self.main_window = widget
                self.watch_status_bar(widget)
                self.log.emit("app", phase="main_window_shown", title=widget.windowTitle())
                if self.on_main_window:
                    self.on_main_window(widget)
            return
        if not isinstance(widget, QDialog):
            return
        key = id(widget)
        if key in self.open_dialogs:
            return
        info = describe_dialog(widget)
        self.open_dialogs[key] = info
        event = self.log.emit("dialog", phase="opened", **info)
        text = " ".join(filter(None, [info.get("message", ""), info.get("informative", "")]))
        reason = raw_error_reason(text)
        if reason:
            self.log.emit("suspicious_text", where=f"dialog '{info['title']}'", text=clip(text, 500),
                          reason=reason, dialog_event=event["seq"])

    def window_hidden(self, widget):
        # Qt deletes many dialogs right after they close (QInputDialog, QMessageBox helpers).
        # A Python wrapper still held at that moment corrupts memory in PySide 6.8, so let go now.
        unpin(widget)
        info = self.open_dialogs.pop(id(widget), None)
        if info is None:
            return
        result = widget.result() if isinstance(widget, QDialog) else None
        outcome = {1: "accepted", 0: "rejected"}.get(result, str(result))
        if isinstance(widget, QMessageBox):
            clicked = widget.clickedButton()
            if clicked is not None:
                outcome = "clicked " + clicked.text().replace("&", "")
        self.last_closed_dialog = {"title": info["title"], "outcome": outcome}
        self.log.emit("dialog", phase="closed", title=info["title"], **{"class": info["class"]}, outcome=outcome)

    def watch_status_bar(self, window):
        bar = window.statusBar()
        if id(bar) in self.watched_status_bars:
            return
        self.watched_status_bars.add(id(bar))

        def changed(message):
            if not message:
                return
            self.log.emit("status", message=clip(message, 1000))
            reason = raw_error_reason(message)
            if reason:
                self.log.emit("suspicious_text", where="status bar", text=clip(message, 500), reason=reason)

        bar.messageChanged.connect(changed)


def install_heartbeat(watchdog):
    """A 100 ms timer on the GUI thread proves the event loop is still turning."""
    timer = QTimer(QApplication.instance())
    timer.setInterval(100)
    timer.timeout.connect(watchdog.beat)
    timer.start()
    return timer
