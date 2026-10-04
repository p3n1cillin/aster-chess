"""Export and independently verify stratified native strategy certificates."""
import hashlib
import json
import pathlib
import random
import struct
import subprocess

import chess

from verify_strategy_proof import verify


def digest(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main():
    directory = pathlib.Path("artifacts/proofs/samples-v1")
    if directory.exists(): raise ValueError("Preserve existing proof samples")
    directory.mkdir(); engine = pathlib.Path("artifacts/publish/proof-dev/Aster.exe")
    rng = random.Random(20261030); cases = []
    for name in ("queen", "rook"):
        path = pathlib.Path("artifacts/validation/major-" + name + "-v1.bin"); raw = path.read_bytes()
        entries = struct.unpack_from("<I", raw, 12)[0]; states = raw[16:16 + entries]
        for side in (0, 1):
            sample = rng.sample([i for i, status in enumerate(states) if status == 3 and i % 2 == side], 8)
            for n, index in enumerate(sample):
                color = n % 2 == 0; p, k, d = index >> 13, (index >> 7) & 63, (index >> 1) & 63
                board = chess.Board.empty()
                board.set_piece_at(p, chess.Piece(chess.QUEEN if name == "queen" else chess.ROOK, color))
                board.set_piece_at(k, chess.Piece(chess.KING, color)); board.set_piece_at(d, chess.Piece(chess.KING, not color))
                board.turn = color if side == 0 else not color
                target = directory / f"{name}-{side}-{n:02d}.json"
                response = subprocess.run([str(engine.resolve()), "certify", str(target), board.fen()], capture_output=True, text=True)
                assert response.returncode == 0, (board.fen(), response.stderr)
                report = verify(json.loads(target.read_text()))
                cases.append({"path": target.as_posix(), "sha256": digest(target), "fen": board.fen(), "piece": name,
                              "strong_side": "white" if color else "black", "turn_role": "strong" if side == 0 else "defender",
                              "verification": report})
    result = {"passed": True, "seed": 20261030, "certificates": cases, "engine_sha256": digest(engine),
              "script_sha256": digest(__file__), "verifier_sha256": digest("scripts/verify_strategy_proof.py"),
              "total_positions": sum(c["verification"]["positions"] for c in cases),
              "total_edges": sum(c["verification"]["edges"] for c in cases),
              "max_positions": max(c["verification"]["positions"] for c in cases)}
    (directory / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": True, "certificates": len(cases), "total_positions": result["total_positions"], "total_edges": result["total_edges"], "max_positions": result["max_positions"]}))


if __name__ == "__main__": main()
