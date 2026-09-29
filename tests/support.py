"""Shared helpers: skip integration tests when DT or Qt cannot run here."""

import os
import subprocess
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

from jev.config import dt_path, host_python

# The suite runs DT headless even on a laptop with a screen; JEV_TEST_DISPLAY=window shows it instead.
os.environ["JEV_DISPLAY"] = os.environ.get("JEV_TEST_DISPLAY", "headless")


@lru_cache(maxsize=1)
def app_available():
    checkout = dt_path()
    if checkout is None:
        return False, "DT checkout not found (set JEV_DT_PATH)"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parents[1]), str(checkout / "src")]))
    probe = subprocess.run([host_python(), "-c", "import PySide6.QtWidgets, dt.ui"], capture_output=True, text=True,
                           env=env, timeout=120)
    if probe.returncode != 0:
        return False, "PySide6/DT not importable: " + probe.stderr.strip().splitlines()[-1]
    return True, ""


def requires_app(test_case):
    available, reason = app_available()
    return unittest.skipUnless(available, reason)(test_case)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jev-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.environ["JEV_HOME"] = str(self.root / "home")
        os.environ["JEV_RUNS_DIR"] = str(self.root / "runs")
