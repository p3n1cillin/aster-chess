"""Cross-check a completed durable match journal, exported PGN and JSON snapshot."""
import argparse
import hashlib
import io
import json
import pathlib

import chess.pgn

from match_recovery import load_completed, validate_resume_configuration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    if output.exists():
        raise ValueError('Preserve previous audit evidence')
    prefix = pathlib.Path(args.prefix)
    paths = {name: pathlib.Path(str(prefix) + suffix) for name, suffix in
             [('report', '.json'), ('pgn', '.pgn'), ('journal', '.journal.jsonl')]}
    report = json.loads(paths['report'].read_text(encoding='utf-8'))
    suite_path = pathlib.Path(report['opening_suite']['path'])
    assert hashlib.sha256(suite_path.read_bytes()).hexdigest() == report['opening_suite']['sha256']
    suite = json.loads(suite_path.read_text(encoding='utf-8'))
    openings = suite['openings'] if isinstance(suite, dict) else suite
    openings = [dict(start_fen=item.get('start_fen', chess.STARTING_FEN), moves=item['moves'])
                if isinstance(item, dict) else dict(start_fen=chess.STARTING_FEN, moves=item)
                for item in openings]
    journal_report, records, _ = load_completed(prefix, openings)
    validate_resume_configuration(journal_report, report)
    assert len(records) == 2 * report['pairs_requested']
    assert journal_report['games'] == report['games']
    for key in ['wins', 'draws', 'losses', 'forfeits', 'unresolved']:
        assert journal_report[key] == report[key]
    with paths['pgn'].open(encoding='utf-8') as stream:
        for detail, text in records:
            exported = chess.pgn.read_game(stream)
            saved = chess.pgn.read_game(io.StringIO(text))
            assert exported is not None and not exported.errors
            assert dict(exported.headers) == dict(saved.headers)
            assert list(exported.mainline_moves()) == list(saved.mainline_moves())
        assert chess.pgn.read_game(stream) is None
    missing = [index + 1 for index, game in enumerate(report['games']) if 'searches' not in game]
    assert len(missing) == report.get('resume', {}).get('pgn_only_games', 0)
    assert all(report['games'][index - 1].get('recovered_from_pgn') and
               report['games'][index - 1]['seconds'] is None for index in missing)
    result = dict(status='passed', games=len(records), unique_ordered_rounds=len(records),
                  missing_telemetry_game_ordinals=missing,
                  checks='Full ordered journal details equal JSON; complete PGN headers/moves equal journal; '
                         'opening hashes, configurations, game rules, outcomes and counters agree.',
                  source_sha256={name: hashlib.sha256(path.read_bytes()).hexdigest()
                                 for name, path in paths.items()},
                  auditor_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest())
    output.write_bytes((json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps(result))


if __name__ == '__main__':
    main()
