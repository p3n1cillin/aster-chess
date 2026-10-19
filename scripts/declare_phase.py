"""Freeze the phase-output ablation before training or candidate queries."""
from research_reference import research_text
import json

from run_rating import digest, write_new
from uci_client import ROOT


def main():
    data = "artifacts/data/teacher-turn-60k-static-v1-classical.jsonl"
    baseline = "artifacts/publish/q-evasion-default-dotnet/Aster.dll"
    exclusions = [*[f"tests/fixtures/openings-v{i}.json" for i in range(1, 6)],
        *[f"tests/fixtures/{name}-parent-v1.json" for name in ("rating", "lazy-order", "q-evasion", "iir")]]
    plan = {"schema": 1, "status": "declared before phase implementation, training and candidate queries",
        "hypothesis": "Shared king-context hidden features with separate turn-aware middlegame/endgame output heads can represent phase-dependent corrections. Only output architecture changes; default classical evaluation remains.",
        "formats": {"9": "hybrid clipped king-context turn-aware phase output", "10": "standalone clipped king-context turn-aware phase output"},
        "phase": "min(24, sum N=1,B=1,R=2,Q=4 for both colors); MG weight phase/24, EG (24-phase)/24; blend signed int64 dots before one integer division",
        "training": {"data": data, "data_sha256": digest(ROOT / data), "hidden": 64, "epochs": 50,
            "batch_size": 512, "learning_rate": .0002, "threads": 4, "seed": 20261014,
            "classical_base": True, "king_context": True, "turn_output": True, "squared_activation": False,
            "activation_bias": .5, "transformer_std": .1, "pair_loss_weight": 1.,
            "control_output": "artifacts/training/phase-control-v1", "candidate_output": "artifacts/training/phase-output-v1",
            "initialization": "Generate the same 2H control output and RNG state, then clone it into MG and EG; same whole-game split, batches, optimizer and loss. Select each epoch by held-out ordinary loss only.",
            "expected_control_sha256": "98535307c0c30b529cf242d2a947ccacf66678b25710f80de980e13ec4c77975"},
        "baseline": baseline, "baseline_sha256": digest(ROOT / baseline),
        "baseline_source": "artifacts/research/q-evasion-default-source/manifest.json",
        "generation": {"positions": 80, "attempts": 1024, "seed": 20261112, "plies": 20, "nodes": 2048, "verify_nodes": 20000, "max_cp": 80,
            "exclude_data": [data, "artifacts/data/teacher-20k-v1.jsonl", "artifacts/data/endgame-diagnostic-512-v1.jsonl"],
            "exclude_suites": exclusions,
            "partitions": "first32 pairs phase vs classical30ms, next32 pairs phase vs matched control30ms, last16 pairs conditional phase vs classical100ms. Freeze before candidate opening queries."},
        "verification": "Existing tests/formats1..8, independent scalar and Python quantized references, phase-only cache changes, captures/promotions/castling/null/undo, signed-int16 extremes, invalid dimensions/payloads, full rules/protocol verifier and bench7. No move-generation change.",
        "tactics": {"tactics-depth8": 32, "tactics-5000nodes": 32, "tactics-quiet-depth8": 32, "tactics-quiet-5000nodes": 25, "endgames-5000nodes": 13},
        "matches": {"short_pairs_each": 32, "seconds_per_move": .03, "conditional_long_pairs": 16, "long_seconds_per_move": .1,
            "resources": {"Threads": 1, "Hash": 64, "Move Overhead": 0, "max_additional_plies": 400},
            "bootstrap_samples": 20000, "bootstrap_seed": 20261113,
            "primary": "First4 legal UCI ply families, preserve whole color-swapped pairs; primary95% interval includes unresolved0/1 bounds"},
        "gate": "Always complete both64-game short matches. Long32-game confirmation only if all correctness/tactical gates pass, zero forfeits/unresolved, classical short family lower strictly>50% and control short point>=50% with family lower>=45%. Promotion additionally requires long point>=50%, lower>=45% and zero forfeits/unresolved. No adaptive extension or parameter tuning.",
        "maximum_games": 160, "rating": "No new Elo calibration in this architecture screen; retain the last exact matched binary's rating. Strength is measured in games, never inferred from teacher error or speed.",
        "limits": research_text('declare_phase.interpretation')}
    write_new(ROOT / "artifacts/research/phase-plan-v1.json", plan)
    print(json.dumps({"declared": True, "plan_sha256": digest(ROOT / "artifacts/research/phase-plan-v1.json"), "maximum_games": 160}))


if __name__ == "__main__": main()
