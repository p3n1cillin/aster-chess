"""Durable match snapshots and validation of completed games during recovery."""
import copy
import hashlib
import io
import json
import os
import pathlib
import tempfile
import time

import chess
import chess.pgn


def atomic_report(path, report, attempts=10):
    """Keep the old snapshot intact if replacement fails; retain the recovery file."""
    path = pathlib.Path(path)
    with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent,
                                    prefix='.' + path.name + '.', suffix='.tmp', delete=False) as stream:
        temporary = pathlib.Path(stream.name)
        stream.write((json.dumps(report, indent=2) + '\n').encode('utf-8'))
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(attempts):
        try:
            os.replace(temporary, path)
            return
        except OSError:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(0.05 * (attempt + 1), 0.25))


def append_journal(stream, entry):
    stream.write(json.dumps(entry, separators=(',', ':')) + '\n')
    stream.flush()
    os.fsync(stream.fileno())


def recount(report):
    for key in ['wins', 'draws', 'losses', 'unresolved', 'forfeits']:
        report[key] = 0
    for detail in report['games']:
        if detail['termination'].startswith('engine forfeit'):
            report['forfeits'] += 1
        result = detail['result']
        key = ('unresolved' if result == '*' else 'draws' if result == '1/2-1/2'
               else 'wins' if (result == '1-0') == (detail['candidate_color'] == 'white') else 'losses')
        report[key] += 1


def _validate_game(game, detail, index, openings, report):
    pair, white = index // 2 + 1, index % 2 == 0
    setup = openings[pair - 1]
    assert not game.errors
    assert game.headers['Round'] == f'{pair}.{1 if white else 2}'
    assert game.headers['White'] == report['candidate_name' if white else 'opponent_name']
    assert game.headers['Black'] == report['opponent_name' if white else 'candidate_name']
    limit = report['limit']
    expected_limit = f"{limit['nodes']} nodes/move" if 'nodes' in limit else f"{limit['seconds_per_move']}s/move"
    assert game.headers['TimeLimit'] == expected_limit
    root = game.board()
    assert root.fen() == chess.Board(setup['start_fen']).fen()
    prefix = setup['moves'].split()
    moves = [move.uci() for move in game.mainline_moves()]
    assert moves[:len(prefix)] == prefix
    opening = chess.Board(setup['start_fen'])
    for move in prefix:
        opening.push_uci(move)
    if detail is None:
        detail = {
            'pair': pair, 'candidate_color': 'white' if white else 'black',
            'opening': setup['moves'], 'starting_fen': setup['start_fen'],
            'initial_fen': opening.fen(), 'result': game.headers['Result'],
            'termination': game.headers['Termination'], 'plies': len(moves), 'seconds': None,
            'recovered_from_pgn': True,
            'telemetry_missing_reason': 'Legacy snapshot failed after PGN flush; retain outcome and moves '
                                        'without inventing per-move telemetry or game wall time.',
        }
    assert detail['pair'] == pair and detail['candidate_color'] == ('white' if white else 'black')
    assert detail['opening'] == setup['moves'] and detail['initial_fen'] == opening.fen()
    assert detail['starting_fen'] == root.fen()
    assert detail['result'] == game.headers['Result']
    assert detail['termination'] == game.headers['Termination'] and detail['plies'] == len(moves)
    if 'searches' in detail:
        assert [s['move'] for s in detail['searches']] == moves[len(prefix):]
    outcome = game.end().board().outcome(claim_draw=True)
    if detail['termination'].startswith('engine forfeit'):
        raise ValueError('An engine forfeit needs investigation before recovery')
    if detail['result'] == '*':
        assert outcome is None
    else:
        assert outcome is not None and outcome.result() == detail['result']
        assert outcome.termination.name.lower() == detail['termination']
    return detail


def load_completed(prefix, openings):
    """Recover exact ordered outcomes, preferring the durable game journal."""
    prefix = pathlib.Path(prefix)
    journal = pathlib.Path(str(prefix) + '.journal.jsonl')
    source_report = pathlib.Path(str(prefix) + '.json')
    source_pgn = pathlib.Path(str(prefix) + '.pgn')
    records = []
    origin = {'prefix': str(prefix.resolve())}
    if journal.exists():
        # An incomplete journal line is an error, not an outcome to silently drop.
        lines = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
        assert lines and lines[0]['type'] == 'header'
        report = copy.deepcopy(lines[0]['summary'])
        for entry in lines[1:]:
            assert entry['type'] == 'game'
            game = chess.pgn.read_game(io.StringIO(entry['pgn']))
            detail = _validate_game(game, entry['detail'], len(records), openings, report)
            records.append((detail, entry['pgn']))
        origin['journal_sha256'] = hashlib.sha256(journal.read_bytes()).hexdigest()
    else:
        report = json.loads(source_report.read_text(encoding='utf-8'))
        pgns = []
        with source_pgn.open(encoding='utf-8') as stream:
            while (game := chess.pgn.read_game(stream)) is not None:
                pgns.append(game)
        saved = report['games']
        assert len(saved) <= len(pgns) <= len(saved) + 1, 'Ambiguous legacy recovery boundary'
        for index, game in enumerate(pgns):
            detail = _validate_game(game, saved[index] if index < len(saved) else None,
                                    index, openings, report)
            records.append((detail, str(game) + '\n\n'))
        origin.update(report_sha256=hashlib.sha256(source_report.read_bytes()).hexdigest(),
                      pgn_sha256=hashlib.sha256(source_pgn.read_bytes()).hexdigest())
    assert len(records) <= 2 * report['pairs_requested']
    report['games'] = [detail for detail, _ in records]
    recount(report)
    origin.update(completed_games=len(records), next_game_ordinal=len(records) + 1,
                  pgn_only_games=sum(bool(detail.get('recovered_from_pgn')) for detail, _ in records),
                  original_runner_sha256=report['runner_sha256'])
    return report, records, origin


def validate_resume_configuration(saved, current):
    for key in ['candidate_binary_sha256', 'opponent_binary_sha256', 'pairs_requested',
                'limit', 'max_plies', 'candidate_options', 'opponent_options',
                'candidate_option_defaults', 'opponent_option_defaults',
                'candidate_name', 'opponent_name', 'opponent_strength_mode']:
        if saved.get(key) != current.get(key):
            raise ValueError('Resume would change match configuration: ' + key)
    if saved['opening_suite']['sha256'] != current['opening_suite']['sha256']:
        raise ValueError('Resume would change opening suite')
