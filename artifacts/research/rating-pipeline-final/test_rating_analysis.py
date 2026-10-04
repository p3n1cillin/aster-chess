"""Check rating math, pairing, clustered weighting and missing-game behavior."""
import math
import unittest

from analyze_rating import bootstrap, equivalent, game_bounds, paired_groups, rating_summary
from run_rating import choose_setting, screen_score


def game(pair, color, result, fen=None):
    return {"pair": pair, "candidate_color": color, "result": result,
            "starting_fen": "start", "opening": "e2e4 e7e5 g1f3 b8c6",
            "initial_fen": fen or f"position-{pair} w - - 0 1"}


class RatingAnalysisTests(unittest.TestCase):
    def test_reference_model_and_limits(self):
        self.assertEqual(equivalent(2300, .5), 2300)
        self.assertAlmostEqual(equivalent(2300, .75), 2490.848501887865)
        self.assertAlmostEqual(equivalent(2300, .25), 2109.151498112135)
        self.assertEqual(equivalent(2300, 0), -math.inf)
        self.assertEqual(equivalent(2300, 1), math.inf)
        with self.assertRaises(ValueError): equivalent(2300, 1.01)

    def test_color_pair_and_family(self):
        rows = [game(1, "white", "1-0"), game(1, "black", "1/2-1/2"),
                game(2, "white", "0-1"), game(2, "black", "0-1")]
        families, pairs, scores = paired_groups(rows, 2)
        self.assertEqual(scores, [(.75, .75), (.5, .5)])
        self.assertEqual(len(families), 1); self.assertEqual(len(pairs), 2)
        self.assertEqual(bootstrap(families, 100, 1), [.625, .625])

    def test_unresolved_bounds_and_suppressed_point(self):
        self.assertEqual(game_bounds(game(1, "black", "*")), (0, 1))
        _, _, scores = paired_groups([game(1, "white", "1-0"), game(1, "black", "*")], 1)
        self.assertEqual(scores, [(.5, 1.)])
        result = rating_summary(2300, scores, [.5, 1], 1)
        self.assertIsNone(result["numeric_local_rating"])
        self.assertIsNone(result["score"])
        self.assertTrue(result["unbounded_upper"])
        self.assertIsNone(result["primary_95_percent_local_interval"][1])

    def test_missing_pair_duplicate_color_repeated_position_rejected(self):
        rows = [game(1, "white", "1-0"), game(1, "black", "0-1")]
        with self.assertRaises(ValueError): paired_groups(rows, 2)
        with self.assertRaises(ValueError): paired_groups([rows[0], rows[0]], 1)
        with self.assertRaises(ValueError):
            paired_groups(rows + [game(2, "white", "1-0", rows[0]["initial_fen"]),
                                  game(2, "black", "0-1", rows[0]["initial_fen"])], 2)

    def test_family_bootstrap_weights_pairs_not_family_means(self):
        # Sampling both families has pair-weighted mean .9; weighting family
        # means instead would wrongly produce .5. Sampling just the large
        # family produces 1 and just the small family 0.
        import random
        from unittest.mock import patch
        groups = [[(0., 0.)], [(1., 1.)] * 9]
        with patch.object(random.Random, "choice", side_effect=[(0., 0., 1), (9., 9., 9)] * 100):
            self.assertEqual(bootstrap(groups, 100, 1), [.9, .9])

    def test_numeric_precision_and_range_gates(self):
        result = rating_summary(2300, [(.5, .5)] * 128, [.4, .6], 0)
        self.assertEqual(result["status"], "provisional local estimate")
        self.assertEqual(result["numeric_local_rating"], 2300)
        result = rating_summary(2300, [(.5, .5)], [.2, .8], 0)
        self.assertIn("Primary interval wider than 200 local units", result["failed_numeric_gates"])
        result = rating_summary(1320, [(.25, .25)], [.2, .3], 0)
        self.assertIn("Point outside supported reference range", result["failed_numeric_gates"])
        self.assertIsNone(result["numeric_local_rating"])

    def test_screen_selection_is_neutral_for_unresolved_and_ties_lower(self):
        tied = {"wins": 1, "draws": 0, "unresolved": 2, "games": [None] * 4}
        self.assertEqual(screen_score(tied), .5)
        self.assertEqual(choose_setting({2300: tied, 1800: tied}), 1800)


if __name__ == "__main__": unittest.main()
