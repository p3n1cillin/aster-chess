"""Apply the predeclared first-four-ply family bootstrap to a frozen Rust screen."""
from research_reference import research_text
import argparse
import collections
import hashlib
import json
import pathlib
import random
import statistics

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report');parser.add_argument('--output',required=True)
    args=parser.parse_args();source=pathlib.Path(args.report);out=pathlib.Path(args.output)
    if out.exists():raise ValueError('Preserve prior analyses')
    data=json.loads(source.read_text(encoding='utf-8'));pairs=collections.defaultdict(list)
    for game in data['games']:pairs[game['pair']].append(game)
    families=collections.defaultdict(list);unresolved=0;points=[]
    for games in pairs.values():
        assert len(games)==2 and {g['candidate_color']for g in games}=={'white','black'}
        if any(g['result']=='*'for g in games):unresolved+=1;continue
        value=sum(.5 if g['result']=='1/2-1/2' else float((g['result']=='1-0')==(g['candidate_color']=='white'))for g in games)/2
        points.append(value);families[(games[0]['starting_fen'],' '.join(games[0]['opening'].split()[:4]))].append(value)
    groups=list(families.values());rng=random.Random(20261019);draws=[]
    for _ in range(20000):draws.append(statistics.mean(v for group in rng.choices(groups,k=len(groups))for v in group))
    draws.sort();report={'score':statistics.mean(points),'family_95_percent_interval':[draws[500],draws[19500]],'families':len(groups),
        'resolved_pairs':len(points),'unresolved_pairs':unresolved,'bootstrap_samples':20000,'seed':20261019,'family_definition':'initial FEN plus first four UCI plies',
        'wins':data['wins'],'draws':data['draws'],'losses':data['losses'],'forfeits':data['forfeits'],
        'report_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'analyzer_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        'interpretation':research_text('analyze_rust_foundation.interpretation')}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':main()
