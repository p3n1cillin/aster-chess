"""Record the fixed Hyperion trial decision after both complete independent audits.

Run from the repository root. This only writes new research records; it never
changes the product's version, source, network pin or model file.
"""
import datetime
import hashlib
import json
import pathlib

import chess.pgn

ROOT = pathlib.Path.cwd()


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def sha(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def write_new(name, data):
    with (ROOT / name).open('xb') as stream:
        stream.write((json.dumps(data, indent=2) + '\n').encode())


def main():
    plan_path = 'artifacts/research/rust-hyperion-plan-v1.json'
    plan = read(plan_path)
    assert sha(plan_path) == '3ac00160e8f537009bcf036957e1d138e63c68be17b6b74bea05e708f4f58c6b'
    candidate = '510ae5e88f0dc6d162602902df1d5778b49fcc8103a7296644b84915489801d7'
    baseline = plan['baseline']['sha256']
    assert sha('artifacts/publish/rust-hyperion-v1/aster.exe') == candidate
    assert sha(plan['baseline']['binary']) == baseline
    provenance = read('artifacts/validation/rust-hyperion-provenance-v1.json')
    assert provenance['status'] == 'passed'
    for name, digest in provenance['immutable_files'].items():
        assert sha(name) == digest
    checks = {'source_and_binary_integrity': True}
    for profile in ['release', 'debug']:
        text = (ROOT / f'artifacts/validation/rust-hyperion-logs/hyperion-{profile}-v1.log').read_text(encoding='utf-8')
        checks[f'{profile}_135_native_tests'] = '135 passed; 0 failed' in text
    for key, name in [('compatible_quantized_layout', 'artifacts/research/rust-hyperion-compatibility-v1.json'),
                      ('independent_rules', 'artifacts/verification/rust-hyperion-v1.json'),
                      ('independent_edges', 'artifacts/verification/rust-hyperion-edges-v1.json'),
                      ('proof_exports', 'artifacts/proofs/rust-hyperion-v1/verification.json')]:
        result = read(name)
        assert result.get('binary_sha256', candidate) == candidate
        checks[key] = result['passed']
    host = read('artifacts/play/rust-hyperion-v1.json')
    assert host['play_binary_sha256'] == host['engine_binary_sha256'] == candidate
    checks['actual_host'] = host['status'] == 'passed'
    puzzles = {}
    for name, gate in [('depth', 'original_depth8_min'), ('quiet', 'quiet_5000nodes_min'),
                       ('endgames', 'endgames_5000nodes_min')]:
        result = read(f'artifacts/tactics/rust-hyperion-v1-{name}.json')
        assert result['binary_sha256'] == candidate
        puzzles[name] = dict(solved=result['solved'], total=result['total'],
                             required=plan['promotion']['tactics'][gate])
        checks['tactics_' + name] = result['solved'] >= puzzles[name]['required']
    matches = []
    for control, prefix, expected_missing in [('30ms', 'rust-hyperion-v1-30ms-complete', [83]),
                                               ('100ms', 'rust-hyperion-v1-100ms', [])]:
        report_path = f'artifacts/matches/{prefix}.json'
        report = read(report_path)
        analysis = read(f'artifacts/matches/rust-hyperion-v1-{control}-family.json')
        audit = read(f'artifacts/validation/rust-hyperion-match-{control}-v1.json')
        journal = read(f'artifacts/validation/rust-hyperion-journal-{control}-v1.json')
        expected = next(m for m in plan['matches'] if m['seconds'] == report['limit']['seconds_per_move'])
        assert len(report['games']) == expected['games'] == audit['games'] == journal['games']
        assert audit['status'] == journal['status'] == 'passed'
        assert journal['missing_telemetry_game_ordinals'] == expected_missing
        assert analysis['report_sha256'] == journal['source_sha256']['report'] == sha(report_path)
        assert report['candidate_binary_sha256'] == candidate and report['opponent_binary_sha256'] == baseline
        assert analysis['bootstrap_samples'] == plan['analysis']['bootstrap_samples']
        assert analysis['seed'] == plan['analysis']['seed']
        if control == '30ms':
            legacy = read('artifacts/matches/rust-hyperion-v1-30ms.json')
            assert len(legacy['games']) == 82 and report['games'][:82] == legacy['games']
            with (ROOT / 'artifacts/matches/rust-hyperion-v1-30ms.pgn').open(encoding='utf-8') as original, \
                 (ROOT / f'artifacts/matches/{prefix}.pgn').open(encoding='utf-8') as completed:
                for _ in range(83):
                    old = chess.pgn.read_game(original)
                    retained = chess.pgn.read_game(completed)
                    assert old is not None and retained is not None
                    assert dict(old.headers) == dict(retained.headers)
                    assert list(old.mainline_moves()) == list(retained.mainline_moves())
                assert chess.pgn.read_game(original) is None
        gate = plan['promotion'][control]
        checks['match_' + control] = (analysis['score'] >= gate['min_score'] and
            analysis['family_95_percent_interval'][0] >= gate['min_family_95_lower'] and
            report['forfeits'] == gate['forfeits'] and report['unresolved'] == gate['unresolved'])
        matches.append(dict(control=control, report=report_path, games=len(report['games']), **analysis))
    candidate_ci = read('artifacts/ci/rust-hyperion-freeze-39182133145.json')
    production_ci = read('artifacts/ci/rust-trial-auditor-39181461967.json')
    checks['candidate_native_windows_linux_ci'] = len(candidate_ci['jobs']) == 2 and all(
        all(any(step['name'] == name and step['conclusion'] == 'success' for step in job['steps'])
            for name in ['Run cargo test --release --locked', 'Run cargo test --locked'])
        for job in candidate_ci['jobs'])
    checks['candidate_windows_linux_ci'] = candidate_ci['conclusion'] == 'success'
    assert production_ci['conclusion'] == 'success'
    assert len(production_ci['jobs']) == 2 and all(job['conclusion'] == 'success' for job in production_ci['jobs'])
    assert sum(m['games'] for m in matches) == 384
    decision_path = 'artifacts/research/rust-hyperion-decision-v1.json'
    decision = dict(schema=1, date='2026-10-19', timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        promote=all(checks.values()), checks=checks, failed_gates=[k for k,v in checks.items() if not v],
        plan_sha256=sha(plan_path), recovery_addendum_sha256=sha('artifacts/research/rust-hyperion-recovery-addendum-v1.json'),
        recorder_sha256=sha('artifacts/research/rust-hyperion-record-v1.py'),
        candidate_binary_sha256=candidate, retained_production_binary_sha256=baseline,
        puzzles=puzzles, matches=matches, candidate_ci=candidate_ci['url'], production_ci=production_ci['url'],
        storage_recovery=dict(retained_before_restart=83, resumed_game_ordinal=84,
            missing_telemetry_game_ordinals=[83], all_outcomes_and_moves_retained=True,
            original_telemetry_records_exact=82, original_pgn_records_exact=83,
            interrupted_prefix='artifacts/matches/rust-hyperion-v1-30ms',
            interrupted_report_is_additional_sample=False,
            note='Original 82-game JSON and 83-game PGN remain unchanged. No replay or sample extension. '
                 'Game 83 search telemetry/wall time unavailable; aggregate elapsed excludes unavailable time/downtime.'),
        interpretation='Apply every fixed gate without retuning. The original tactical gate fails, so retain '
            'Rust 0.9.2/v109 regardless of match scores. An expected-move miss does not prove globally weaker play. '
            'Playing-strength improvement requires a family lower bound above .5; absolute/public Elo and '
            'Stockfish superiority need separate predeclared tests. Local desktop has no affinity/isolation.',
        public_elo=None, rust_rating=None, full_strength_stockfish_superiority=False)
    assert not decision['promote'] and not checks['tactics_depth']
    write_new(decision_path, decision)
    rating = read('artifacts/ratings/session-20261018-legal-probe.json')
    for key in ['decision', 'same_work_timing_ratio', 'paired_regressions', 'limits', 'status', 'timestamp_utc']:
        rating.pop(key, None)
    rating.update(date='2026-10-19', timestamp_utc=decision['timestamp_utc'],
        status='Hyperion trial complete and rejected; production remains Rust 0.9.2/v109, unrated.',
        decision=decision_path, rejected_candidate_binary_sha256=candidate, neural_trial_matches=matches,
        limits='Historical C# calibration stays attached only to its frozen binary. This model trial is against '
               'Rust 0.9.2, not a Stockfish rating calibration. No upstream/public Elo is transferred. '
               'One game lacks telemetry but has complete moves and outcome; no local CPU affinity/isolation.')
    write_new('artifacts/ratings/session-20261019-hyperion.json', rating)
    print(json.dumps(dict(promote=decision['promote'], failed_gates=decision['failed_gates'], games=384)))


if __name__ == '__main__':
    main()
