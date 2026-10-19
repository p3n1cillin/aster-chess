"""Freeze exact Rust sources, toolchain, model pin and standalone binary before matches."""
from research_reference import research_text
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess

ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--cargo-feature', action='append', default=[], help='Exact feature used for this binary; repeatable')
    parser.add_argument('--pgo-manifest', help='Pinned PGO build report for this exact binary')
    parser.add_argument('--pgo-role', choices=['control', 'optimized'], default='optimized')
    args=parser.parse_args();binary=pathlib.Path(args.binary).resolve();directory=pathlib.Path(args.directory).resolve()
    if directory.exists():raise ValueError('Preserve prior frozen source')
    directory.mkdir(parents=True)
    paths=[ROOT/name for name in ['Cargo.toml','Cargo.lock','rust-toolchain.toml','.cargo/config.toml','requirements-dev.txt','LICENSE','THIRD_PARTY_NOTICES.md']]
    paths+=sorted(p for p in (ROOT/'crates/engine').rglob('*') if p.is_file() and p.name!='viridithas.nnue.zst')
    paths+=sorted(p for p in (ROOT/'crates/aster-core').rglob('*') if p.is_file() and p.suffix!='.nnue')
    paths+=[ROOT/'scripts'/name for name in ['freeze_rust.py','fetch_rust_network.py','fetch_aster_network.py','fetch_reference.py','research_reference.py','research-reference.json','verify_source_names.py','verify_disagreement_guard.py','analyze_disagreement.py','verify_aster_branding.py','tactics.py','verify.py','verify_rust.py','verify_rust_equivalence.py','smoke_rust_play.py','smoke_mate_proof.py','verify_mate_proof.py','verify_rust_proofs.py','match.py','match_recovery.py','uci_client.py','build.ps1','play.ps1','rust-paths.ps1','benchmark_rust_legal_probe.py']]
    entries=[]
    paths += [ROOT / 'scripts' / 'benchmark_indexed_accumulators.py']
    paths += [ROOT / 'scripts' / name for name in ['verify_evaluation_risk.py', 'verify_evaluation_risk_lifecycle.py', 'analyze_evaluation_risk.py']]
    paths += [ROOT / 'scripts' / name for name in ['build_pgo.py', 'benchmark_pgo.py', 'verify_pgo_driver.py', 'verify_pgo_runtime.py', 'analyze_pgo.py']]
    for path in sorted(paths):
        relative=path.relative_to(ROOT);target=directory/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        entries.append({'path':relative.as_posix(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    cargo=shutil.which('cargo') or str(pathlib.Path.home()/'.cargo/bin/cargo.exe')
    rustc=shutil.which('rustc') or str(pathlib.Path.home()/'.cargo/bin/rustc.exe')
    provenance = None
    description = None
    if args.pgo_manifest:
        build_path = pathlib.Path(args.pgo_manifest).resolve()
        build = json.loads(build_path.read_text(encoding='utf-8'))
        selected = build['binaries'][args.pgo_role]
        if build['status'] != 'built_unqualified' or selected['sha256'] != hashlib.sha256(binary.read_bytes()).hexdigest():
            raise ValueError('PGO build report does not match this binary')
        shutil.copy2(build_path, directory / 'pgo-build.json')
        provenance = {'role': args.pgo_role, 'manifest_file': 'pgo-build.json',
                      'manifest_sha256': hashlib.sha256(build_path.read_bytes()).hexdigest(),
                      'compiler_flags': selected['rustflags'], 'profile_guided': args.pgo_role == 'optimized'}
        if args.pgo_role == 'optimized':
            profile = pathlib.Path(build['merged_profile']['path'])
            if hashlib.sha256(profile.read_bytes()).hexdigest() != build['merged_profile']['sha256']:
                raise ValueError('Merged profile changed after compilation')
            shutil.copy2(profile, directory / 'merged.profdata')
            provenance['profile'] = {'file': 'merged.profdata', 'sha256': build['merged_profile']['sha256']}
        command = next(step['argv'] for step in build['steps'] if step['label'] == 'build-' + args.pgo_role)
        description = ' '.join(command) + '; compiler flags and build provenance recorded in pgo-build.json; role=' + args.pgo_role
    report={'binary':str(binary),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
        'build':'cargo build --workspace --release --locked' + ''.join(' --features ' + feature for feature in args.cargo_feature) + '; x86-64-v3 flags from .cargo/config.toml; no PGO; core embed-net enabled by engine dependency',
        'cargo_features':args.cargo_feature,
        'cargo':subprocess.check_output([cargo,'--version'],text=True).strip(),
        'compiler':subprocess.check_output([rustc,'-Vv'],text=True).strip(),
        'network':json.loads((ROOT/'crates/aster-core/UPSTREAM.json').read_text(encoding='utf-8'))['network'],
        'upstream':json.loads((ROOT/'crates/aster-core/UPSTREAM.json').read_text(encoding='utf-8')),
        'legacy_network':json.loads((ROOT/'crates/engine/NETWORK.json').read_text(encoding='utf-8')),
        'legacy_upstream':{'repository':'https://github.com/cosmobobak/viridithas','tag':'v20.0.0','commit':'0631113e2215714c54d397cce9a8caebc5e6f8ee','license':'MIT at pinned release'},
        'runtime':'Standalone Rust engine and Rust HTTP host; no external engine, python-chess, C/C++ build, C tablebase or .NET runtime',
        'source_files':entries,'note':research_text('freeze_rust.interpretation')}
    if provenance is not None:
        report['pgo'] = provenance
        report['build'] = description
    (directory/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'binary_sha256':report['binary_sha256'],'source_files':len(entries)}))

if __name__=='__main__':main()
