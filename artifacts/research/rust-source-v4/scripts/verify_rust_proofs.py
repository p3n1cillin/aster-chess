"""Re-export every saved general-material fixture with Rust and independently verify it."""
import argparse
import hashlib
import json
import pathlib
import subprocess

from uci_client import DEFAULT_ENGINE, engine_command, ROOT
from verify_mate_proof import verify

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',default=str(DEFAULT_ENGINE))
    parser.add_argument('--directory',required=True)
    args=parser.parse_args();out=pathlib.Path(args.directory)
    if out.exists():raise ValueError('Preserve prior native exports')
    out.mkdir(parents=True);checked=[];failed=[]
    for source in sorted((ROOT/'artifacts/proofs/mate-proof-general-v2').glob('*.json')):
        old=json.loads(source.read_text(encoding='utf-8'))
        if not old.get('complete'):continue
        destination=out/source.name
        result=subprocess.run([*engine_command(args.engine),'certify-mate',str(destination),str(old['maxPlies']),
            'white'if old['strongSide']==0 else'black',old['rootFen']],capture_output=True,text=True)
        if result.returncode:
            failed.append({'source':source.name,'exit_code':result.returncode,'output':result.stdout+result.stderr});continue
        certificate=json.loads(destination.read_text(encoding='utf-8'));audit=verify(certificate)
        checked.append({'source':source.relative_to(ROOT).as_posix(),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'certificate':destination.name,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
            'visits':certificate['visits'],**audit})
    report={'passed':not failed,'binary_sha256':hashlib.sha256(pathlib.Path(args.engine).read_bytes()).hexdigest(),
        'verifier_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        'rules_verifier_sha256':hashlib.sha256((ROOT/'scripts/verify_mate_proof.py').read_bytes()).hexdigest(),
        'certificates':len(checked),'checked':checked,'failed':failed}
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':not failed,'certificates':len(checked),'positions':sum(x['positions']for x in checked),'failures':failed}))
    if failed:raise RuntimeError('Rust certificate migration failures')

if __name__=='__main__':main()
