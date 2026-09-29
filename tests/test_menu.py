"""The menu: key parsing, filtering, and the commands each path builds (no terminal needed)."""

import io
import os
import unittest

from jev import menu
from jev.menu import BACK, Choice, Picker, Style, parse_keys

from support import TempDirTestCase


class ScriptedUI:
    """Answers each question with the choice whose label starts with the next scripted answer."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.style = Style(False)
        self.asked = []

    def choose(self, title, choices, subtitle="", default=0, back_label="back"):
        self.asked.append(title)
        answer = self.answers.pop(0)
        if answer is BACK:
            return BACK
        for choice in choices:
            if choice.label.startswith(answer):
                return choice.value
        raise AssertionError(f"{answer!r} is not among {[choice.label for choice in choices]} for {title!r}")

    def text(self, prompt, default=""):
        return self.answers.pop(0)

    def pause(self):
        pass


class KeyTests(unittest.TestCase):
    def test_terminal_bytes_become_keys(self):
        self.assertEqual(parse_keys(b"\x1b[A\x1b[B\r"), ["up", "down", "enter"])
        self.assertEqual(parse_keys(b"ab\x7f"), ["a", "b", "backspace"])
        self.assertEqual(parse_keys(b"\x1b"), ["esc"])
        self.assertEqual(parse_keys("é".encode()), ["é"])
        self.assertEqual(parse_keys(b"\x1b[200~x"), ["x"], "unknown sequences are skipped")
        with self.assertRaises(KeyboardInterrupt):
            parse_keys(b"\x03")


class PickerTests(unittest.TestCase):
    def picker(self, count=4):
        choices = [Choice("Run a full campaign", "campaign", "everything"), Choice("Issues", "issues", "list"),
                   Choice("Run one scenario", "scenario", "a known-issue check"), Choice("Quit", "quit")][:count]
        return Picker("What?", choices, style=Style(False), out=io.StringIO())

    def test_arrows_wrap_and_enter_chooses(self):
        picker = self.picker()
        picker.handle("up")
        self.assertEqual(picker.handle("enter").value, "quit")
        picker.handle("down")
        self.assertEqual(picker.handle("enter").value, "campaign")

    def test_typing_filters_and_ranks_label_matches_first(self):
        picker = self.picker()
        for char in "issu":
            picker.handle(char)
        self.assertEqual([choice.value for choice in picker.visible()], ["issues", "scenario"])
        self.assertEqual(picker.handle("enter").value, "issues")
        picker.handle("esc")
        self.assertEqual(picker.query, "", "Esc first clears the filter")
        self.assertIs(picker.handle("esc"), BACK)

    def test_number_keys_pick_in_short_lists(self):
        self.assertEqual(self.picker().handle("2").value, "issues")

    def test_drawing_fits_the_terminal_width(self):
        picker = self.picker()
        lines = picker.lines()
        self.assertTrue(lines[0].startswith("? What?"))
        self.assertTrue(any("Run a full campaign" in line and "everything" in line for line in lines))


class MenuActionTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.saved_key = os.environ.pop("OPENROUTER_API_KEY", None)
        self.addCleanup(lambda: self.saved_key and os.environ.__setitem__("OPENROUTER_API_KEY", self.saved_key))

    def test_crawl_asks_state_length_and_display(self):
        ui = ScriptedUI(["First run", "100 steps", "Headless"])
        argv = menu.action_crawl(ui)
        self.assertEqual(argv[:5], ["crawl", "--seed", "none", "--steps", "100"])
        self.assertEqual(argv[-1], "--headless")

    def test_campaign_without_a_key_skips_the_budget_question(self):
        ui = ScriptedUI(["Use my setting"])
        self.assertEqual(menu.action_campaign(ui), ["campaign", "--budget", "0"])
        self.assertEqual(ui.asked, ["Where should DT run?"])

    def test_issue_paths(self):
        self.assertEqual(menu.action_verify(ScriptedUI(["JEV-0003", "Headless"])),
                         ["verify", "--issue", "JEV-0003", "--headless"])
        self.assertEqual(menu.action_issues(ScriptedUI(["Read", "JEV-0002"])), ["issues", "show", "JEV-0002"])
        self.assertEqual(menu.action_issues(ScriptedUI(["Record", "JEV-0007", "By design", "see README"])),
                         ["issues", "set", "JEV-0007", "--status", "by-design", "--note", "see README"])
        self.assertIs(menu.action_issues(ScriptedUI([BACK])), BACK)

    def test_menu_runs_the_command_and_returns(self):
        ran = []
        ui = ScriptedUI(["Display mode", "Headless", "Check setup", "Quit"])
        self.assertEqual(menu.run_menu(ui, runner=lambda argv: ran.append(argv) or 0), 0)
        self.assertEqual(ran, [["display", "headless"], ["doctor"]])


if __name__ == "__main__":
    unittest.main()
