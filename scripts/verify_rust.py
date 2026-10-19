"""Independent rules, undo, perft, protocol and observer verification of the Rust engine."""
import argparse
import hashlib
import json
import pathlib
import random
import re
import time

import chess

from uci_client import DEFAULT_ENGINE, UciClient
from verify import SPECIAL_FENS, reference_perft, validate_pv

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',default=str(DEFAULT_ENGINE))
    parser.add_argument('--output')
    parser.add_argument('--games',type=int,default=16)
    parser.add_argument('--plies',type=int,default=100)
    parser.add_argument('--setups',type=int,default=0)
    args=parser.parse_args();rng=random.Random(20261018);checked=0;perfts=[];samples=0
    def same(a,b):return chess.Board(a).fen()==chess.Board(b).fen()
    with UciClient(args.engine) as client:
        client.send('setoption name Hash value 64');client.ready()
        def position(board,history=False):
            nonlocal checked
            command='position fen '+board.fen(en_passant='fen')
            if history:command='position startpos moves '+' '.join(m.uci() for m in board.move_stack)
            client.send(command)
            line=client.command('legal','info string legal')
            assert set(line.removeprefix('info string legal').split())=={m.uci() for m in board.legal_moves},board.fen()
            exists=client.command('legal-exists','info string legal-exists ')
            assert exists=='info string legal-exists '+str(bool(list(board.legal_moves))).lower(),(board.fen(),exists)
            actual=client.command('d','info string fen ').removeprefix('info string fen ')
            assert same(actual,board.fen()),(actual,board.fen())
            checked+=1
        for fen in SPECIAL_FENS:
            board=chess.Board(fen);position(board)
            depth=3 if board.legal_moves.count()<40 else 2
            expected=reference_perft(board,depth)
            line=client.command('go perft '+str(depth),'info depth ')
            assert int(line.split(' nodes ')[1].split()[0])==expected
            perfts.append({'fen':fen,'depth':depth,'nodes':expected})
            position(board)
        for _ in range(args.games):
            board=chess.Board()
            for ply in range(args.plies):
                position(board,history=True)
                if board.outcome(claim_draw=True):break
                board.push(rng.choice(list(board.legal_moves)))
        # Random reachable positions supplement the deterministic history games.
        for _ in range(args.setups):
            board=chess.Board()
            for _ in range(rng.randrange(1,70)):
                if board.outcome(claim_draw=True):break
                board.push(rng.choice(list(board.legal_moves)))
            position(board,history=True)
        root=chess.Board();position(root)
        outputs=[]
        for tracing in (False,True):
            client.send('ucinewgame');client.send('aster-trace '+('on' if tracing else 'off'))
            client.send('position startpos');client.send('go depth 9')
            lines=client.until('bestmove',timeout=30);validate_pv(root,lines)
            info=[line for line in lines if line.startswith('info depth ') and ' pv ' in line][-1]
            outputs.append({'bestmove':lines[-1],'score':re.search(r'score (cp|mate) (-?\d+)',info).group(0),
                'nodes':info.split(' nodes ')[1].split()[0]})
            for line in lines:
                if not line.startswith('info string aster-trace '):continue
                frame=json.loads(line.removeprefix('info string aster-trace '));board=root.copy()
                for move in frame['line']:
                    if move=='null':
                        halfmove=board.halfmove_clock;board.push(chess.Move.null());board.halfmove_clock=halfmove
                    else:board.push_uci(move)
                assert same(board.fen(),frame['fen']),(board.fen(),frame)
                assert len(frame['destinationVisits'])==64 and frame['mainCalls']+frame['qCalls']>0
                for row in frame['rootMoves']:
                    assert chess.Move.from_uci(row['move']) in root.legal_moves
                    assert row['nodes']>=0
                    if frame['finished']:assert not row['searching']
                samples+=1
        assert outputs[0]==outputs[1],outputs
        assert samples>0
        client.send('aster-trace on');client.send('position startpos');client.send('go infinite')
        time.sleep(.35);client.send('isready');start=time.monotonic()
        lines=client.until('readyok',timeout=2);assert not any(line.startswith('bestmove') for line in lines)
        ready_seconds=time.monotonic()-start
        branches=0
        for line in lines:
            if not line.startswith('info string aster-trace '):continue
            frame=json.loads(line.removeprefix('info string aster-trace '));board=root.copy()
            for move in frame['line']:
                if move=='null':
                    clock=board.halfmove_clock;board.push(chess.Move.null());board.halfmove_clock=clock
                else:board.push_uci(move)
            assert same(board.fen(),frame['fen']),(board.fen(),frame)
            branches+=bool(frame['line'])
        assert branches>0,'No actual searched branch was observed'

        client.send('stop');lines=client.until('bestmove',timeout=3);validate_pv(root,lines)
        position(root)
        # A fifty-move draw must be claimed (FIDE 9.3), so with the clock at 100 the
        # side to move may still mate: the reference engine 19 core reports Ra8# as mate 1.
        # The legacy Viridithas-derived core always treats the claimable draw as final.
        legacy=('Viridithas' in client.name)
        for fen,expected in [('7k/6Q1/6K1/8/8/8/8/8 b - - 100 1','score mate 0'),('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1','score cp 0'),
                             ('7k/8/6K1/8/8/8/8/R7 w - - 100 1','score cp 0' if legacy else 'score mate 1')]:
            client.send('position fen '+fen);client.send('go depth 2');lines=client.until('bestmove')
            assert any(expected in line for line in lines),lines
    report={'passed':True,'positions':checked,'legal_existence_checks':checked,'perft':perfts,'ready_during_infinite_search_seconds':ready_seconds,
        'observer_equivalence':outputs,'independently_replayed_samples':samples,'independently_replayed_live_branches':branches,
        'binary_sha256':hashlib.sha256(pathlib.Path(args.engine).read_bytes()).hexdigest(),
        'verifier_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}
    if args.output:
        path=pathlib.Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():raise ValueError('Preserve prior verification reports')
        path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'positions':checked,'perft_checks':len(perfts),'observer_samples':samples}))

if __name__=='__main__':main()
