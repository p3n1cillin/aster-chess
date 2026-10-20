"""Audit and symbolize a completed fixed diagnostic, without running an engine."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def checked(path, expected):
    assert digest(path) == expected, str(path)


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def normalize(text):
    return [re.sub(r'\b(nps|time) \d+', r'\1 <timing>', line)
            for line in text.splitlines() if line.startswith(('info depth ', 'bestmove '))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    collection, directory, output = [Path(p).resolve() for p in
                                      [args.collection, args.directory, args.output]]
    assert not directory.exists() and not output.exists(), 'Preserve prior analyses'
    data = load(collection)
    assert data['status'] == 'collected' and data['production_unchanged']
    plan = load(data['plan'])
    checked(data['plan'], data['plan_sha256'])
    checked(ROOT / 'scripts/profile_automatic.py', data['collector_sha256'])
    for entry in plan['playing_inputs']:
        checked(ROOT / entry['path'], entry['sha256'])
    for workload in plan['workloads'].values():
        if 'input' in workload:
            checked(ROOT / workload['input'], workload['input_sha256'])
            checked(ROOT / workload['parent'], workload['parent_sha256'])
    for tool in plan['tools'].values():
        checked(tool['path'], tool['sha256'])
    for binary in data['binaries'].values():
        checked(binary['path'], binary['sha256'])
        for name in ['pdb', 'map']:
            if name in binary:
                checked(binary[name], binary[name + '_sha256'])
    schedule = [{k: r[k] for k in ['workload', 'repetition', 'role']} for r in data['runs']]
    assert schedule == plan['schedule'] and len(schedule) == 32
    checked(data['binaries']['production']['path'], plan['production_sha256'])
    sampler_runs, addresses = [], set()
    counters = []
    for ordinal, run in enumerate(data['runs']):
        assert ordinal == run['ordinal']
        folder = Path(run['folder'])
        for name in ['stdout', 'stderr']:
            checked(folder / (name + '.txt'), run[name + '_sha256'])
        out = (folder / 'stdout.txt').read_text(encoding='utf-8')
        err = (folder / 'stderr.txt').read_text(encoding='utf-8')
        reference = data['normalized_reference'][run['workload']]
        assert normalize(out) == reference
        workload = plan['workloads'][run['workload']]
        assert sum(s.startswith('bestmove ') for s in reference) == workload['searches']
        assert int(re.search(r'Nodes searched\s*:\s*(\d+)', err)[1]) == run['nodes']
        assert int(re.search(r'Total time \(ms\)\s*:\s*(\d+)', err)[1]) == run['bench_ms']
        if 'expected_nodes' in workload:
            assert run['nodes'] == workload['expected_nodes']
        if run['role'] == 'counters':
            parsed = {name: {'ticks': int(ticks), 'calls': int(calls)} for name, ticks, calls in
                      re.findall(r'^\s*([\w+]+):\s+(\d+) cycles\s+(\d+) calls', err, re.M)}
            assert parsed == run['counters'] and len(parsed) == 11
            counters.append(dict(workload=run['workload'], repetition=run['repetition'], counters=parsed))
        if run['role'] == 'sampler':
            for name in ['samples.txt', 'callers.txt']:
                checked(run[name]['path'], run[name]['sha256'])
            pcs = [int(s, 16) for s in Path(run['samples.txt']['path']).read_text().splitlines() if s.strip()]
            outside = int(re.search(r'sampler: (\d+) samples outside the executable', err)[1])
            assert len(pcs) == run['raw_pc_samples'] and outside == run['outside_samples']
            modules = {name: int(n) for n, name in re.findall(r'^\s+(\d+)  (.+)$', err, re.M)}
            assert sum(modules.values()) == outside
            sampler_runs.append((run, Counter(pcs), outside, modules))
            addresses.update(pcs)
    directory.mkdir(parents=True)
    address_file = directory / 'addresses.txt'
    address_file.write_text(''.join(f'0x{pc:x}\n' for pc in sorted(addresses)), encoding='utf-8')
    command = [plan['tools']['llvm-symbolizer']['path'],
               '--obj=' + data['binaries']['sampler']['path'], '--relative-address',
               '--inlines', '--demangle', '--output-style=JSON']
    raw, errors = directory / 'symbolizer.jsonl', directory / 'symbolizer.stderr.txt'
    with address_file.open('rb') as inp, raw.open('xb') as out, errors.open('xb') as err:
        result = subprocess.run(command, stdin=inp, stdout=out, stderr=err, timeout=120)
    assert result.returncode == 0
    symbols = {}
    for line in raw.read_text(encoding='utf-8').splitlines():
        entry = json.loads(line)
        pc = int(entry['Address'], 16)
        assert pc not in symbols
        symbols[pc] = entry.get('Symbol', [])
    assert set(symbols) == addresses
    sections = data['binaries']['sampler']['pe']['sections']
    text = next(s for s in sections if s['name'] == '.text')
    attribution = {}
    source_lines = {}
    for pc, frames in symbols.items():
        code = text['rva'] <= pc < text['rva'] + text['virtual_size']
        resolved = code and any(f.get('FunctionName') and f['FunctionName'] != '??' for f in frames)
        engine = None
        for frame in frames:
            filename = frame.get('FileName', '').replace('\\', '/')
            marker = '/crates/aster-core/'
            if marker in filename:
                relative = 'crates/aster-core/' + filename.split(marker, 1)[1]
                if relative not in source_lines:
                    source_lines[relative] = len((ROOT / relative).read_text(encoding='utf-8').splitlines())
                line = frame.get('Line', 0)
                if 1 <= line <= source_lines[relative]:
                    engine = (frame.get('FunctionName') or '<unnamed>', f'{relative}:{line}')
                    break
        leaf = next((f.get('FunctionName') for f in frames if f.get('FunctionName') not in [None, '', '??']), '<unresolved>')
        if not code:
            function, location = '<non-code RVA>', '<non-code RVA>'
        elif engine:
            function, location = engine
        elif resolved:
            function, location = '<non-engine> ' + leaf, '<resolved without valid engine source line>'
        else:
            function, location = '<unresolved>', '<unresolved>'
        attribution[pc] = dict(code=code, resolved=bool(resolved), engine=engine is not None,
                               function=function, location=location, leaf=leaf)
    write(directory / 'attribution.json', {f'0x{pc:x}': value for pc, value in sorted(attribution.items())})
    summaries, overhead = {}, {}
    for workload in plan['workloads']:
        by_rep, function_counts, line_counts, leaf_counts = [], Counter(), Counter(), Counter()
        totals = Counter()
        for run, counts, outside, modules in sampler_runs:
            if run['workload'] != workload:
                continue
            functions, lines, leaves = Counter({'<outside executable>': outside}), Counter({'<outside executable>': outside}), Counter({'<outside executable>': outside})
            executable = resolved = engine = 0
            for pc, count in counts.items():
                item = attribution[pc]
                executable += count * item['code']
                resolved += count * item['resolved']
                engine += count * (item['code'] and item['engine'])
                functions[item['function']] += count
                lines[item['location']] += count
                leaves[item['leaf'] if item['code'] else '<non-code RVA>'] += count
            population = sum(counts.values()) + outside
            assert sum(functions.values()) == sum(lines.values()) == sum(leaves.values()) == population
            resolution = resolved / executable if executable else 0
            by_rep.append(dict(repetition=run['repetition'], total_samples=population,
                               executable_code_samples=executable, non_code_rvas=sum(counts.values())-executable,
                               resolved_executable_samples=resolved, valid_engine_line_samples=engine,
                               resolved_fraction=resolution, minimum_samples_pass=executable >= 100,
                               resolution_pass=resolution >= 0.8, outside_samples=outside, outside_modules=modules,
                               functions=dict(functions), lines=dict(lines)))
            function_counts.update(functions)
            line_counts.update(lines)
            leaf_counts.update(leaves)
            totals.update(total_samples=population, executable_code_samples=executable,
                          resolved_executable_samples=resolved, valid_engine_line_samples=engine, outside_samples=outside)
        def ranked(counts, field):
            return [dict(name=name, samples=count, fraction=count/totals['total_samples'],
                         repetition_fraction_min=min(r[field].get(name, 0)/r['total_samples'] for r in by_rep),
                         repetition_fraction_max=max(r[field].get(name, 0)/r['total_samples'] for r in by_rep))
                    for name, count in counts.most_common()]
        summaries[workload] = dict(totals=dict(totals), repetitions=by_rep,
                                   functions=ranked(function_counts, 'functions'), lines=ranked(line_counts, 'lines'),
                                   leaf_functions=[dict(name=k, samples=v, fraction=v/totals['total_samples']) for k, v in leaf_counts.most_common()])
        runs = {(r['repetition'], r['role']): r for r in data['runs'] if r['workload'] == workload}
        ratios = {}
        for metric in ['bench_ms', 'wall_ns']:
            ratios[metric] = {}
            for denominator in ['production', 'debug_control']:
                for role in ['debug_control', 'counters', 'sampler']:
                    if role == denominator:
                        continue
                    values = [runs[(i, role)][metric]/runs[(i, denominator)][metric] for i in range(4)]
                    ratios[metric][role + '/' + denominator] = dict(repetitions=values, median=statistics.median(values))
        ratios['heavy_perturbation'] = any(ratios['bench_ms'][role + '/debug_control']['median'] > 2.0
                                          for role in ['counters', 'sampler'])
        overhead[workload] = ratios
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(), status='analyzed',
                  collection=dict(path=str(collection), sha256=digest(collection)),
                  plan=dict(path=data['plan'], sha256=data['plan_sha256']),
                  analyzer_sha256=digest(__file__), symbolizer_command=command,
                  symbolization_files=[dict(path=str(p), sha256=digest(p)) for p in
                                       [address_file, raw, errors, directory/'attribution.json']],
                  unique_rvas=len(addresses), schedule_exact=True, all_traces_exact=True,
                  playing_inputs_unchanged=True, sampling=summaries, overhead=overhead, inclusive_counters=counters,
                  gates=dict(sample_minima=all(r['minimum_samples_pass'] for s in summaries.values() for r in s['repetitions']),
                             resolution=all(r['resolution_pass'] for s in summaries.values() for r in s['repetitions']),
                             overhead=not any(r['heavy_perturbation'] for r in overhead.values())),
                  limitations=[plan['gates']['limits'], 'Exclusive first valid engine inline frame attribution; not a call stack. Full population includes outside/non-code/unresolved samples. Leaf symbols also reported.',
                               'Only emitted outside module counts are available, not raw outside PCs. Caller heuristics archived but unused.',
                               'Four repetitions are descriptive; no independent-sample confidence intervals. This diagnostic establishes no speed or playing-strength gain.'])
    write(output, report)
    print(json.dumps(dict(status=report['status'], unique_rvas=len(addresses), gates=report['gates'], overhead=overhead)))


if __name__ == '__main__':
    main()
