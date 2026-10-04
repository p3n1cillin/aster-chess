"""Check opt-in weakness settings and rejection before match play."""
import unittest

import chess.engine

from match import configure


class FakeEngine:
    def __init__(self, limited=True):
        self.options = {"Hash": chess.engine.Option("Hash", "spin", 64, 1, 1024, None)}
        if limited:
            self.options.update({"UCI_Elo": chess.engine.Option("UCI_Elo", "spin", 1320, 1320, 3190, None),
                                 "UCI_LimitStrength": chess.engine.Option("UCI_LimitStrength", "check", False, None, None, None)})
        self.applied = None
    def configure(self, values): self.applied = dict(values)


class StrengthTests(unittest.TestCase):
    def test_default_does_not_weaken_engine(self):
        engine = FakeEngine(); settings = configure(engine, 64)
        self.assertNotIn("UCI_Elo", settings); self.assertNotIn("UCI_LimitStrength", settings)

    def test_explicit_setting_enables_limit(self):
        engine = FakeEngine(); settings = configure(engine, 64, uci_elo=1800)
        self.assertEqual(engine.applied, settings)
        self.assertEqual(settings["UCI_Elo"], 1800); self.assertTrue(settings["UCI_LimitStrength"])

    def test_unsupported_and_out_of_range_rejected_before_configure(self):
        for engine, value in ((FakeEngine(False), 1800), (FakeEngine(), 1319), (FakeEngine(), 3191)):
            with self.subTest(value=value), self.assertRaises(ValueError): configure(engine, 64, uci_elo=value)
            self.assertIsNone(engine.applied)


if __name__ == "__main__": unittest.main()
