"""Predeclare and generate fresh held-out openings before querying the Rust candidate."""
from research_reference import research_text
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

def main():
    plan_path=ROOT/'artifacts/research/rust-foundation-plan-v1.json'
    if plan_path.exists(): raise ValueError('Preserve predeclared plans')
    suites=[]
    for path in sorted((ROOT/'tests/fixtures').glob('*.json')):
        data=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data,dict) and 'openings' in data:
            suites.append({'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    plan={'date':'2026-10-18','status':'predeclared before candidate queries on these openings',
        'candidate':'Aster Rust 0.9.0 derived from Viridithas 20, commit 0631113e2215714c54d397cce9a8caebc5e6f8ee',
        'network_sha256':'066c172e22c25ee3d3b4084ad44ff761426f906a9c536cabd0127d17413d0585',
        'playing_changes':'No heuristic or evaluation tuning; source integration, diagnostics, certificates, UI and UCI readiness. Correctness repairs must be recorded and frozen before matches.',
        'generation':{'positions':64,'attempts':2048,'seed':20261018,'plies':20,'selection_nodes':2048,'verification_nodes':20000,'max_abs_teacher_cp':80,'excluded_suites':suites},
        'matches':[{'opponent':'frozen original visual-play-dev Aster','pairs':32,'range':[0,32]},
            {'opponent':research_text('reference.full_strength_description'),'pairs':32,'range':[32,64]}],
        'resources':{'seconds_per_move':0.03,'threads':1,'hash_mib':64,'move_overhead':0,'move_overhead_policy':'zero where option exists; report unsupported options','extra_ply_cap':400,'adjudication':'rules only; unresolved never counted as draws'},
        'analysis':{'bootstrap_samples':20000,'seed':20261019,'cluster':'first four UCI opening plies','interpretation':'local screening only; no absolute Elo or universal superiority inferred'},
        'retuning':'No adaptive tuning or extra match games based on outcomes; retain all 128 games and any failures',
        'gates':['Rust native tests/perft','independent legality and PV replay','certificate independent replay','HTTP/SSE smoke','paired matches with exact provenance']}
    plan_path.parent.mkdir(parents=True,exist_ok=True)
    plan_path.write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    command=[sys.executable,str(ROOT/'scripts/generate_openings.py'),'--positions','64','--attempts','2048','--seed','20261018','--plies','20','--nodes','2048','--verify-nodes','20000','--max-cp','80','--output','tests/fixtures/rust-foundation-parent-v1.json']
    for suite in suites:command+=['--exclude-suite',suite['path']]
    print(json.dumps({'plan_sha256':hashlib.sha256(plan_path.read_bytes()).hexdigest(),'excluded_suites':len(suites)}),flush=True)
    subprocess.run(command,cwd=ROOT,check=True)
    parent=ROOT/'tests/fixtures/rust-foundation-parent-v1.json';data=json.loads(parent.read_text(encoding='utf-8'))
    for name,start,end in [('original',0,32),(research_text('legacy_opponent_key'),32,64)]:
        split=dict(data);split['openings']=data['openings'][start:end];split['partition']=[start,end]
        split['parent_sha256']=hashlib.sha256(parent.read_bytes()).hexdigest()
        (ROOT/f'tests/fixtures/rust-foundation-{name}-v1.json').write_text(json.dumps(split,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
