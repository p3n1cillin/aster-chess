"""Apply fixed PGO speed and engineering regression gates; never rate from speed."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from analyze_disagreement import control_report

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'artifacts/verification/aster-pgo-'


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError('Preserve earlier decisions')
    evidence = {}

    def read(path):
        evidence[path] = digest(path)
        return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))

    plan_path = 'artifacts/research/aster-pgo-plan-v2.json'
    plan = read(plan_path)
    build = read('artifacts/research/aster-pgo-build-v2.json')
    assert build['status'] == 'built_unqualified' and build['plan_sha256'] == digest(plan_path)
    assert all(build['search_profile_coverage'].values())
    assert hashlib.sha256(Path(build['merged_profile']['path']).read_bytes()).hexdigest() == build['merged_profile']['sha256']
    binaries = {role: build['binaries'][label]['sha256'] for role, label in [('candidate', 'optimized'), ('opponent', 'control')]}
    parent = read(plan['validation_suite']['path'])
    assert digest(plan['validation_suite']['path']) == plan['validation_suite']['sha256']
    timing_suite = 'tests/fixtures/aster-pgo-timing-v1.json'
    assert read(timing_suite)['openings'] == parent['openings'][:16]
    manifests = {}
    for role, folder in [('candidate', 'aster-pgo-source-v2'), ('opponent', 'aster-pgo-control-source-v2')]:
        path = f'artifacts/research/{folder}/manifest.json'
        manifest = read(path)
        assert manifest['binary_sha256'] == binaries[role]
        base = ROOT / path
        for item in manifest['source_files']:
            assert hashlib.sha256((base.parent / item['path']).read_bytes()).hexdigest() == item['sha256']
        assert hashlib.sha256((base.parent / manifest['pgo']['manifest_file']).read_bytes()).hexdigest() == manifest['pgo']['manifest_sha256']
        if manifest['pgo']['profile_guided']:
            profile = manifest['pgo']['profile']
            assert hashlib.sha256((base.parent / profile['file']).read_bytes()).hexdigest() == profile['sha256'] == build['merged_profile']['sha256']
        manifests[role] = digest(path)
    timing = read(PREFIX + 'timing-v2.json')
    assert timing['complete'] and timing['identical_behavior'] and timing['training_root_overlap'] == 0
    assert timing['plan_sha256'] == digest(plan_path)
    assert timing['build_report_sha256'] == digest('artifacts/research/aster-pgo-build-v2.json')
    assert timing['suite_sha256'] == digest(timing_suite)
    for mode in plan['timing']['modes']:
        assert len(timing['modes'][mode]['batches']) == plan['timing']['replicates']
    for check in ['runtime', 'control-equivalence', 'control-driver', 'optimized-driver', 'source-integrity', 'rules', 'edges', 'play', 'proofs', 'analysis-source-names']:
        result = read(PREFIX + check + '-v2.json')
        assert result.get('passed') or result.get('status') == 'passed', check
    for mode in ['auto', 'avx2', 'scalar']:
        eq = read(PREFIX + f'equivalence-{mode}-v2.json')
        assert eq['passed'] and eq['identical'] == eq['positions'] == 96
        for suite in ['tactics-v1', 'tactics-quiet-v1', 'endgames-v1']:
            tactical = read(f'artifacts/tactics/aster-pgo-{mode}-candidate-{suite}-v2.json')
            assert tactical['reference_match'] and tactical['binary_sha256'] == binaries['candidate']
    for profile in ['release', 'default-debug', 'default-release']:
        path = PREFIX + profile + '-tests-v2.log'
        evidence[path] = digest(path)
        rows = re.findall(r'test result: (\w+)\. (\d+) passed; (\d+) failed', (ROOT / path).read_text(encoding='utf-8-sig'))
        assert sum(int(r[1]) for r in rows) == 159 and all(r[0] == 'ok' and r[2] == '0' for r in rows)
    ci = read(PREFIX + 'ci-jobs-v2.json')
    assert len(ci['jobs']) == 2 and all(j['conclusion'] == 'success' for j in ci['jobs'])
    controls = {}
    for name, specification in plan['matches'].items():
        path = f'artifacts/matches/aster-pgo-{name}-v2.json'
        raw = read(path)
        for role, binary in binaries.items():
            assert raw[role + '_binary_sha256'] == binary
            assert raw[role + '_source_manifest']['sha256'] == manifests[role]
        suite_path = f'tests/fixtures/aster-pgo-{name}-v1.json'
        first, last = specification['suite_range']
        assert read(suite_path)['openings'] == parent['openings'][first:last]
        assert raw['opening_suite']['sha256'] == digest(suite_path)
        control = control_report(ROOT / path, specification['pairs'], specification['seconds_per_move'])
        interval = control.get('opening_family_95_percent_interval')
        control['passes_engineering_nonregression'] = bool(
            control['resolved_pairs'] == specification['pairs'] and control['unresolved_pairs'] == 0
            and raw['forfeits'] == 0 and interval and interval[1] >= 0.5)
        controls[name] = control
        for kind in ['pgn', 'journal']:
            audit = read(PREFIX + f'{name}-{kind}-audit-v2.json')
            assert audit['status'] == 'passed' and audit['games'] == 2 * specification['pairs']
            if kind == 'journal':
                assert audit['source_sha256']['report'] == digest(path)
    adopted = timing['passed'] and all(c['passes_engineering_nonregression'] for c in controls.values())
    report = {'adopted': adopted, 'timing_passed': timing['passed'], 'controls': controls,
              'platform': plan['build']['host'], 'matched_profile_sha256': build['merged_profile']['sha256'],
              'binary_sha256': binaries['candidate'], 'evidence_sha256': evidence,
              'analyzer_sha256': digest('scripts/analyze_pgo.py'),
              'interpretation': 'Engineering speed/nonregression screen on roots excluded from compiler training. The reference-strength gate is separate. No absolute/public Elo or superiority follows from compilation speed; ordinary builds remain available.'}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'adopted': adopted, 'controls': controls}))


if __name__ == '__main__':
    main()
