"""Compare complete fixed-depth behavior on fresh positions before Rust safety promotion."""
import argparse
import hashlib
import json
import pathlib
import chess
import chess.engine
from uci_client import engine_command

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',required=True);parser.add_argument('--baseline',required=True)
    parser.add_argument('--suite',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();out=pathlib.Path(args.output)
    if out.exists():raise ValueError('Preserve previous comparisons')
    suite=pathlib.Path(args.suite);positions=json.loads(suite.read_text(encoding='utf-8'))['openings'];results=[]
    for role,path in [('baseline',args.baseline),('candidate',args.candidate)]:
        observed=[]
        with chess.engine.SimpleEngine.popen_uci(engine_command(path),timeout=30) as engine:
            engine.configure({'Hash':64,'Threads':1})
            for entry in positions:
                board=chess.Board()
                for move in entry['moves'].split():board.push_uci(move)
                info=engine.analyse(board,chess.engine.Limit(depth=9),game=object())
                observed.append({'depth':info['depth'],'nodes':info['nodes'],'cp':info['score'].white().score(),
                    'mate':info['score'].white().mate(),'pv':[m.uci()for m in info['pv']]})
        results.append({'role':role,'binary_sha256':hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest(),'observed':observed})
    matches=[a==b for a,b in zip(results[0]['observed'],results[1]['observed'],strict=True)]
    report={'passed':all(matches),'positions':len(matches),'identical':sum(matches),'results':results,
        'suite_sha256':hashlib.sha256(suite.read_bytes()).hexdigest(),'checker_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        'interpretation':'Same ordinary fixed-depth decisions and work; no timed strength or Elo is inferred. The explicit maximum-depth regression intentionally changes a formerly crashing edge case.'}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({'passed':report['passed'],'identical':sum(matches),'positions':len(matches)}))
    if not all(matches):raise RuntimeError('Unexpected ordinary search behavior change')

if __name__=='__main__':main()
