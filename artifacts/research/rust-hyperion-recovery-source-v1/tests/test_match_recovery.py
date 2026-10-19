"""Storage-fault and exact-sample recovery checks; no engine processes required."""
import copy
import errno
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import chess
import chess.pgn
from match_recovery import append_journal, atomic_report, load_completed, validate_resume_configuration


class RecoveryTests(unittest.TestCase):
    def fixture(self, directory):
        prefix = pathlib.Path(directory) / 'match'
        board = chess.Board()
        for move in ['f2f3', 'e7e5', 'g2g4', 'd8h4']:
            board.push_uci(move)
        game = chess.pgn.Game.from_board(board)
        game.headers.update(Round='1.1', White='candidate', Black='baseline',
                            Result='0-1', Termination='checkmate', TimeLimit='0.03s/move')
        report = dict(pairs_requested=1, games=[], candidate_name='candidate', opponent_name='baseline',
                      runner_sha256='old-runner', candidate_binary_sha256='candidate-sha',
                      opponent_binary_sha256='baseline-sha', limit={'seconds_per_move': .03},
                      max_plies=400, candidate_options={'Hash': 64, 'Threads': 1},
                      opponent_options={'Hash': 64, 'Threads': 1},
                      candidate_option_defaults={}, opponent_option_defaults={},
                      opponent_strength_mode='engine defaults', opening_suite={'sha256': 'suite-sha'})
        detail = dict(pair=1, candidate_color='white', opening='', starting_fen=chess.STARTING_FEN,
                      initial_fen=chess.STARTING_FEN, result='0-1', termination='checkmate',
                      plies=4, seconds=1.2, searches=[{'move': move.uci()} for move in board.move_stack])
        snapshot = prefix.with_suffix('.json')
        snapshot.write_text(json.dumps(report), encoding='utf-8')
        prefix.with_suffix('.pgn').write_text(str(game) + '\n\n', encoding='utf-8')
        return prefix, report, detail, str(game) + '\n\n', [{'start_fen': chess.STARTING_FEN, 'moves': ''}]

    def test_legacy_pgn_ahead_retains_game_without_fabricated_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix, report, _, _, openings = self.fixture(directory)
            before = prefix.with_suffix('.json').read_bytes()
            saved, records, origin = load_completed(prefix, openings)
            self.assertEqual(len(records), 1)
            self.assertEqual(origin['next_game_ordinal'], 2)
            self.assertEqual(origin['pgn_only_games'], 1)
            self.assertEqual(saved['losses'], 1)
            self.assertNotIn('searches', saved['games'][0])
            self.assertIsNone(saved['games'][0]['seconds'])
            self.assertEqual(prefix.with_suffix('.json').read_bytes(), before)

    def test_failed_snapshot_keeps_old_file_and_journal_retains_full_game(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix, report, detail, pgn, openings = self.fixture(directory)
            before = prefix.with_suffix('.json').read_bytes()
            with pathlib.Path(str(prefix) + '.journal.jsonl').open('w', encoding='utf-8') as journal:
                append_journal(journal, {'type': 'header', 'summary': report})
                append_journal(journal, {'type': 'game', 'detail': detail, 'pgn': pgn})
            complete = dict(report, games=[detail])
            with patch('match_recovery.os.replace', side_effect=OSError(errno.EINVAL, 'simulated report fault')):
                with self.assertRaises(OSError):
                    atomic_report(prefix.with_suffix('.json'), complete, attempts=1)
            self.assertEqual(prefix.with_suffix('.json').read_bytes(), before)
            self.assertEqual(len(list(pathlib.Path(directory).glob('.match.json.*.tmp'))), 1)
            saved, _, origin = load_completed(prefix, openings)
            self.assertEqual(saved['games'][0]['searches'], detail['searches'])
            self.assertEqual(origin['pgn_only_games'], 0)

    def test_changed_resource_or_opening_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            _, report, _, _, _ = self.fixture(directory)
            changed = copy.deepcopy(report)
            changed['limit'] = {'seconds_per_move': .1}
            with self.assertRaises(ValueError):
                validate_resume_configuration(report, changed)
            changed = copy.deepcopy(report)
            changed['opening_suite']['sha256'] = 'other-suite'
            with self.assertRaises(ValueError):
                validate_resume_configuration(report, changed)

    def test_ambiguous_extra_legacy_games_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix, _, _, pgn, openings = self.fixture(directory)
            prefix.with_suffix('.pgn').write_text(pgn + pgn, encoding='utf-8')
            with self.assertRaises(AssertionError):
                load_completed(prefix, openings)

    def test_truncated_journal_record_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix, report, _, _, openings = self.fixture(directory)
            pathlib.Path(str(prefix) + '.journal.jsonl').write_text(
                json.dumps({'type': 'header', 'summary': report}) + '\n{"type":"game",', encoding='utf-8')
            with self.assertRaises(json.JSONDecodeError):
                load_completed(prefix, openings)


if __name__ == '__main__':
    unittest.main()
