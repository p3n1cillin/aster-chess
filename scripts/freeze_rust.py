"""Freeze exact Rust sources, toolchain, model pin and standalone binary before matches."""
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
    args=parser.parse_args();binary=pathlib.Path(args.binary).resolve();directory=pathlib.Path(args.directory).resolve()
    if directory.exists():raise ValueError('Preserve prior frozen source')
    directory.mkdir(parents=True)
    paths=[ROOT/name for name in ['Cargo.toml','Cargo.lock','rust-toolchain.toml','.cargo/config.toml','requirements-dev.txt','LICENSE','THIRD_PARTY_NOTICES.md']]
    paths+=sorted(p for p in (ROOT/'crates/engine').rglob('*') if p.is_file() and p.name!='viridithas.nnue.zst')
    paths+=[ROOT/'scripts'/name for name in ['freeze_rust.py','fetch_rust_network.py','verify.py','verify_rust.py','verify_rust_equivalence.py','smoke_rust_play.py','verify_mate_proof.py','verify_rust_proofs.py','match.py','match_recovery.py','uci_client.py','build.ps1','play.ps1','rust-paths.ps1','benchmark_rust_legal_probe.py']]
    entries=[]
    for path in sorted(paths):
        relative=path.relative_to(ROOT);target=directory/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        entries.append({'path':relative.as_posix(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    cargo=shutil.which('cargo') or str(pathlib.Path.home()/'.cargo/bin/cargo.exe')
    rustc=shutil.which('rustc') or str(pathlib.Path.home()/'.cargo/bin/rustc.exe')
    report={'binary':str(binary),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
        'build':'cargo build --release --locked; x86-64-v3 flags from .cargo/config.toml; no PGO; no optional features',
        'cargo':subprocess.check_output([cargo,'--version'],text=True).strip(),
        'compiler':subprocess.check_output([rustc,'-Vv'],text=True).strip(),
        'network':json.loads((ROOT/'crates/engine/NETWORK.json').read_text(encoding='utf-8')),
        'upstream':{'repository':'https://github.com/cosmobobak/viridithas','tag':'v20.0.0','commit':'0631113e2215714c54d397cce9a8caebc5e6f8ee','license':'MIT at pinned release'},
        'runtime':'Standalone Rust engine and Rust HTTP host; no external engine, python-chess, C/C++ build, C tablebase or .NET runtime',
        'source_files':entries,'note':'Compressed weights are reproducibly fetched from the immutable URL and SHA-256-checked by build.rs. The standalone binary embeds them. Fingerprints below preserve source, Cargo dependency lock, model/license pin and build scripts. No Elo or Stockfish superiority inferred.'}
    (directory/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'binary_sha256':report['binary_sha256'],'source_files':len(entries)}))

if __name__=='__main__':main()
