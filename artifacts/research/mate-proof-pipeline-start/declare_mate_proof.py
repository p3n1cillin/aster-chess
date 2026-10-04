"""Declare bounded general mate certificates and unchanged-play regression checks."""
import json

from run_rating import digest, write_new
from uci_client import ROOT


def main():
    baseline = "artifacts/publish/phase-dev/Aster.dll"
    plan = {"schema": 1, "status": "declared before general proof implementation or candidate queries",
        "capability": "Original exhaustive bounded AND/OR mate search, any standard-chess material, independent rules-only certificate verification. One legal attacker continuation, every legal defense, every leaf actual mate. No Stockfish/table runtime dependency.",
        "limits": {"maximum_plies": 7, "default_visits": 50000, "maximum_visits": 100000,
            "history": "Fresh FEN origin or reset halfmove clock; reject unsupported prior reversible history. Conservatively require root clock+requested bound<100 except existing terminal checkmate. With at most7 plies, a fresh legal position cannot recur three times (minimum return cycle4 plies). Independent verifier replays exact full FEN/clocks and draw rules on every branch."},
        "algorithm": "Iterative bounds0..7, all legal moves, prioritize attacker checks/captures without pruning other moves, defender AND coverage; total visit budget spans iterations, cancellation polled. No hash-only success caching or failed-branch certificate nodes. Strictly decreasing actual upper bounds and complete reachable tree only; mate distance need not be globally optimal.",
        "interface": "certify-mate <newpath> <plies0..7> <white|black> <FEN>; explain mate [plies0..7] [visits1..100000]. Plain explain retains native KQK/KRK explanations and falls back for other material. Protocol-clean background worker; isready/stop/quit responsive and speculative finally undo.",
        "baseline": baseline, "baseline_sha256": digest(ROOT / baseline), "baseline_source": "artifacts/research/phase-source/manifest.json",
        "verification": "Full required build/tests/rule/perft/protocol/bench checks; scalar tree verifier replays every branch and handles terminal mate before clock draws. Mate1/longer, defender-root, promotions, en passant/castling, insufficient material, stalemate, history/clock/budget/cancellation cases; corruption rejects missing defenses, illegal edges, altered clocks, cycles, bounds, false leaves, unreachable nodes and false root claims. Existing certificates still verify. Independent bounded Python differential on seeded cases; budget unknowns never labelled losses.",
        "behavior": "No playing search/evaluation changes. Compare exact default move/score/node outputs on32 fresh held-out openings at depth8, and original/quiet/endgame tactical thresholds. Preserve source fingerprints to verify unchanged playing code.",
        "generation": {"positions": 32, "attempts": 512, "seed": 20261114, "plies": 20, "nodes": 2048, "verify_nodes": 20000, "max_cp": 80,
            "exclude_data": ["artifacts/data/teacher-turn-60k-static-v1-classical.jsonl", "artifacts/data/teacher-20k-v1.jsonl", "artifacts/data/endgame-diagnostic-512-v1.jsonl"],
            "exclude_suites": [*[f"tests/fixtures/openings-v{i}.json" for i in range(1,6)], *[f"tests/fixtures/{n}-parent-v1.json" for n in ("rating","lazy-order","q-evasion","iir","phase")]]},
        "paired_regression": {"pairs": 16, "seconds_per_move": .03, "max_additional_plies": 400, "Threads": 1, "Hash": 64, "Move Overhead": 0,
            "gate": "All32 games complete and independently audited, no forfeits/unresolved; point score is descriptive only because playing code is unchanged. No Elo or strength gain inferred."},
        "success": "Independent general certificates and all correctness/protocol/unchanged-playing gates. Budgets may produce unproven results, never guarantees. Native capability expansion is distinct from unachieved full-strength Stockfish playing superiority.",
        "no_adaptive_extension": True, "rating": "Retain exact0.7.6-q-evasion local2319 reference; changed interface build not separately calibrated."}
    write_new(ROOT / "artifacts/research/mate-proof-plan-v1.json", plan)
    print(json.dumps({"declared": True, "plan_sha256": digest(ROOT / "artifacts/research/mate-proof-plan-v1.json")}))


if __name__ == "__main__": main()
