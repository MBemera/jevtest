"""Window mode: DT on a real screen, each step highlighted, the person's own input ignored.

These tests need a desktop display (on Linux servers: `Xvfb :99 &` and `DISPLAY=:99`). The input
guard test also needs xdotool, which sends real X11 mouse clicks.
"""

import base64
import os
import shutil
import subprocess
import unittest

from jev.config import display_available, display_setting, resolve_display
from jev.session import AppSession

from support import TempDirTestCase, requires_app


class DisplaySettingTests(TempDirTestCase):
    def test_option_beats_environment_beats_saved_setting(self):
        from jev.config import save_setting
        saved = os.environ.pop("JEV_DISPLAY", None)
        self.addCleanup(lambda: os.environ.__setitem__("JEV_DISPLAY", saved) if saved is not None else None)
        save_setting("display", "window")
        self.assertEqual(display_setting(), ("window", display_setting()[1]))
        os.environ["JEV_DISPLAY"] = "headless"
        self.assertEqual(resolve_display(), "headless")
        self.assertEqual(resolve_display("window"), "window")
        self.assertEqual(resolve_display("visible"), "window")
        with self.assertRaises(ValueError):
            resolve_display("sideways")

    def test_headless_sessions_render_offscreen(self):
        session = AppSession(self.root / "app", display="headless")
        self.assertEqual(session.environment()["QT_QPA_PLATFORM"].split(":")[0], "offscreen")
        self.assertEqual(session.options["pace"], 0.0)
        window = AppSession(self.root / "app2", display="window")
        self.assertNotIn("QT_QPA_PLATFORM", window.environment())
        self.assertGreater(window.options["pace"], 0)


def pink_pixels(png_base64):
    """Pixels in the highlight colour, counted with Qt (the test interpreter has PySide6 with DT)."""
    from PySide6.QtGui import QColor, QImage
    image = QImage.fromData(base64.b64decode(png_base64))
    count = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            colour = QColor(image.pixel(x, y))
            if abs(colour.red() - 236) < 20 and abs(colour.green() - 64) < 20 and abs(colour.blue() - 122) < 20:
                count += 1
    return count


@requires_app
@unittest.skipUnless(display_available(), "no desktop display (on Linux, run Xvfb and set DISPLAY)")
class WindowModeTests(TempDirTestCase):
    def start(self, name="app", **options):
        session = AppSession(self.root / name, display="window", seed="sample", pace=0.2, **options)
        session.start()
        self.addCleanup(session.stop)
        return session

    def test_steps_are_highlighted_but_screenshots_stay_clean(self):
        session = self.start()
        session.act("click", ref="New assessment", jev_step=7, snapshot=False)
        state = session.call("state")
        self.assertEqual(state["display"], "window")
        self.assertIn('step 7: Click "New assessment"', state["highlight"])
        shot = session.call("screenshot", {})
        try:
            self.assertEqual(pink_pixels(shot["png_base64"]), 0, "Jev's screenshots must show DT only")
        except ImportError:
            pass
        session.call("wait", {"seconds": 1})
        self.assertIn("waiting", session.call("state")["highlight"])

    @unittest.skipUnless(shutil.which("xdotool") and os.environ.get("DISPLAY"), "needs xdotool on X11")
    def test_real_clicks_are_ignored_unless_input_is_allowed(self):
        for allow, expected in ((False, 3), (True, 4)):
            session = self.start(name=f"app-{allow}", allow_input=allow)
            nodes = session.call("snapshot", {})["nodes"]
            button = next(node for node in nodes if node["name"] == "New assessment")
            x, y, width, height = button["rect"]
            subprocess.run(["xdotool", "mousemove", str(x + width // 2), str(y + height // 2), "click", "1"],
                           check=True, timeout=20)
            session.call("wait", {"seconds": 1.5})
            rows = next(node for node in session.call("snapshot", {})["nodes"] if node["role"] == "list")
            self.assertEqual(rows["count"], expected, f"allow_input={allow}")
            session.stop()


if __name__ == "__main__":
    unittest.main()
