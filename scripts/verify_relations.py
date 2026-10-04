"""Independent geometric feature and nonzero synthetic model inference checks."""
import json
import random
import subprocess
import sys

import chess
import numpy as np

from neural_format import RELATION_FEATURES, attack_feature_bins, feature_indices, save_model
from run_rating import digest, write_new
from uci_client import DEFAULT_ENGINE, ROOT, UciClient
from verify import SPECIAL_FENS


def main():
    directory = ROOT / "artifacts/research/relations-synthetic-v1"
    directory.mkdir(exist_ok=False)
    rng = random.Random(20261126)
    fens = list(SPECIAL_FENS) + [
        "4k3/4n3/8/3P4/8/8/8/K3R3 w - - 0 1",
        "4k3/4n3/8/3P4/8/8/3R4/K3R3 w - - 0 1",
        "7k/8/8/2b5/8/4P3/4R3/K7 w - - 0 1",
        "7k/8/8/PPPP4/rrrr4/8/8/7K w - - 0 1"]
    checked = 0; bins_seen = set()
    with UciClient() as client:
        for fen in fens + [chess.STARTING_FEN] * 40:
            board = chess.Board(fen)
            for ply in range(80):
                expected = attack_feature_bins(board)
                client.send("position fen " + board.fen(en_passant="fen"))
                actual = list(map(int,client.command("nnattacks","info string nnattacks ").split()[3:]))
                assert actual == expected,(board.fen(),actual,expected)
                bins_seen.update(expected)
                for perspective in (chess.WHITE,chess.BLACK):
                    features = feature_indices(board,perspective,True,True)
                    assert len(features) == len(board.piece_map())*2+20
                    assert len(set(features)) == len(features) and max(features) < RELATION_FEATURES
                    flipped = board.copy(); flipped.turn = not board.turn
                    assert features == feature_indices(flipped,perspective,True,True)
                    assert sorted(features) == sorted(feature_indices(board.mirror(),not perspective,True,True))
                checked += 1
                moves = list(board.legal_moves)
                if not moves: break
                board.push(rng.choice(moves))
    assert checked > 3000 and bins_seen == {0,1,2,3}
    generator = np.random.default_rng(20261126)
    results = []
    for hidden,hybrid in ((16,True),(256,False)):
        model = directory / f"synthetic-h{hidden}.ann"
        # Signed, nonzero weights on all features catch index mistakes hidden by zero initialization.
        linear = generator.integers(-35,36,RELATION_FEATURES).astype(float)/100
        weights = generator.integers(-24,25,(RELATION_FEATURES,hidden)).astype(float)/256
        output = generator.integers(-16000,16001,hidden*4).astype(float)/(100*256)
        save_model(model,linear,np.full(hidden,.5),weights,output,hybrid,True,True,False,True,True)
        report = ROOT / f"artifacts/validation/relations-synthetic-h{hidden}-network.json"
        with (report.with_suffix(".txt")).open("x",encoding="utf-8") as log:
            subprocess.run([sys.executable,str(ROOT / "scripts/verify_network.py"),str(model),"--output",str(report)],stdout=log,stderr=subprocess.STDOUT,check=True)
        results.append({"model":model.relative_to(ROOT).as_posix(),"sha256":digest(model),"report":report.relative_to(ROOT).as_posix(),"report_sha256":digest(report)})
    result = {"passed":True,"script_sha256":digest(__file__),"engine_sha256":digest(DEFAULT_ENGINE),
        "geometric_positions":checked,"all_count_bins_seen":sorted(bins_seen),"turn_independence_and_mirror_symmetry":True,
        "synthetic_nonzero_models":results,"scope":"Independent python-chess geometric reference and scalar quantized inference; development dependencies only."}
    write_new(ROOT / "artifacts/validation/relations-geometry-v1.json",result)
    print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
