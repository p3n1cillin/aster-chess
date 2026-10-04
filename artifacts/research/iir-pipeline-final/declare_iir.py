"""Declare the bounded IIR experiment before candidate behavior/match queries."""
import json

from run_rating import digest, write_new
from uci_client import ROOT


def main():
    candidate = "artifacts/publish/iir-dev/Aster.dll"
    baseline = "artifacts/publish/q-evasion-default-dotnet/Aster.dll"
    plan = {"schema":1,"status":"declared before candidate behavior, fixture generation and matches",
        "hypothesis":"A one-ply reduction at depth>=5 without a TT move reallocates work from unseeded nonPV branches. Root/PV/check/history/rule50/mate-bound/pawn-only safeguards remain. Store only reduced searched depth. No parameter tuning or combination with rejected experiments.",
        "candidate":candidate,"candidate_sha256":digest(ROOT / candidate),"candidate_source":"artifacts/research/iir-source/manifest.json",
        "baseline":baseline,"baseline_sha256":digest(ROOT / baseline),"baseline_source":"artifacts/research/q-evasion-default-source/manifest.json",
        "generation":{"positions":448,"attempts":4096,"seed":20261108,"plies":20,"nodes":2048,"verify_nodes":20000,"max_cp":80,
            "partition":"First256 pairs30ms; next64 pairs100ms; final128 conditional rating. Behavior first32 of each regression partition. All frozen before Aster queries.",
            "exclude_data":["artifacts/data/teacher-20k-v1.jsonl","artifacts/data/teacher-turn-augmented-60k-v1.jsonl","artifacts/data/endgame-diagnostic-v1.jsonl"],
            "exclude_suites":[*[f"tests/fixtures/openings-v{i}.json" for i in range(1,6)],"tests/fixtures/rating-parent-v1.json","tests/fixtures/lazy-order-parent-v1.json","tests/fixtures/q-evasion-parent-v1.json"]},
        "correctness":"52 candidate C# tests, including actual TT stored-depth/guarded-root/PV/clock/pawn cases; full required legality/perft/protocol verifier. Speculative undo, terminal precedence and legal PVs preserved.",
        "tactics":{"tactics-depth8":32,"tactics-5000nodes":32,"tactics-quiet-depth8":32,"tactics-quiet-5000nodes":25,"endgames-5000nodes":13},
        "behavior":"64 depth8 opening comparisons and256 seeded warm/history/FEN/rule50/searchmoves cases, with independent legality/root-restoration checks. Changed nodes/scores expected; no same-work gate. Instrumented depth9 must demonstrate trigger; profiling is not strength.",
        "matches":[{"label":"30ms","pairs":256,"seconds_per_move":.03,"minimum_score":.5,"family_lower_strictly_above":.5},
                   {"label":"100ms","pairs":64,"seconds_per_move":.1,"minimum_score":.5,"minimum_family_lower":.45}],
        "resources":{"Threads":1,"Hash":64,"Move Overhead":0,"max_additional_plies":400},
        "uncertainty":{"bootstrap_samples":20000,"seed":20261109,"primary":"First4 legal UCI ply families, retain both colors and every pair; unresolved0/1 bounds included"},
        "promotion":"All correctness/tactical/profile/behavior gates, zero forfeits/unresolved, primary family lower>50% at30ms and score>=50% with lower>=45% at100ms. Otherwise opt-in. No superiority claim across engines/controls from this regression.",
        "conditional_rating":{"pairs":128,"setting":2300,"seconds_per_move":.03,"opponent_sha256":"45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0",
            "model":"2300+400*log10(p/(1-p)); localSF19 strength-setting equivalent, one thread64MiB, not public Elo",
            "numeric_gates":"All896 games audited, zero unresolved/forfeits, finite primary CI<=200units and point/CI within1320..3190. No rating transfer to a different binary."},
        "no_adaptive_extension":True,"maximum_game_budget":896,
        "decision":"Always complete640 regression games, even failed tactics. Conditional256 rating games only if frozen promotion gates pass. Preserve every result, binary/source, options/control/openings/hardware/PGN/audit. No retuning after outcomes. Full-strength Stockfish superiority remains unachieved."}
    write_new(ROOT / "artifacts/research/iir-plan-v1.json",plan)
    print(json.dumps({"declared":True,"candidate_sha256":plan["candidate_sha256"],"maximum_games":896}))


if __name__ == "__main__": main()
