"""Freeze a nested H64/H128 capacity comparison before initialization/training."""
import json

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    prior = read(ROOT / "artifacts/research/deep-turn-plan-v1.json")
    bundle = read(ROOT / "artifacts/research/deep-turn-training-data-v1.json")
    decision = read(ROOT / "artifacts/research/deep-turn-decision-v1.json")
    assert not decision["eligible_for_promotion"] and bundle["complete"]
    plan = {"schema":1,"status":"Declared before nested initialization, new training or opening/candidate queries",
        "hypothesis":"Increasing hidden capacity from64 to128 improves playing strength on unchanged data and objective. Extra output weights start zero, preserving the H64 initial function; fresh-pair loss remains zero for both roles, following the completed stronger control.",
        "prior_experiment":"artifacts/research/deep-turn-experiment-v1-manifest.json",
        "prior_experiment_sha256":digest(ROOT / "artifacts/research/deep-turn-experiment-v1-manifest.json"),
        "data":bundle["data"],"data_sha256":bundle["data_sha256"],"split_path":bundle["split_path"],"split_sha256":bundle["split_sha256"],
        "data_bundle":"artifacts/research/deep-turn-training-data-v1.json","data_bundle_sha256":digest(ROOT / "artifacts/research/deep-turn-training-data-v1.json"),
        "baseline":prior["baseline"],"baseline_sha256":prior["baseline_sha256"],"baseline_source":prior["baseline_source"],
        "training":{**{key:prior["training"][key] for key in ("epochs","batch_size","learning_rate","threads","seed","classical_base","king_context","turn_output","phase_output","squared_activation","activation_bias","transformer_std","pair_loss_weight")},
            "control_hidden":64,"candidate_hidden":128,"fresh_pair_loss_weight":0.,"extra_initial_seed":20261123,
            "initialization":"Recreate the original H64 initial state and post-initialization Torch RNG. Embed every shared column and four output blocks unchanged in H128; add independent seeded ordinary-feature columns, zero king-context/padding columns, bias0.5 and zero extra outputs. Freeze both explicit initialization files. Same post-H64 RNG restored before batch shuffles; dimensions differ, so complete state hashes cannot match. Verify shared tensors, zero extra outputs and initial function within0.0001cp on all63826 rows; no labels select initialization.",
            "control_reproduction":"H64 must reproduce the prior deep-turn control model byte for byte, with identical selected epoch, full initial state, RNG and all50 batch-order hashes. A failure stops before candidate training.",
            "selection":"Only shared ordinary held-out target loss selects each epoch. Capacity is the sole intended model change; no different data, loss weights, budgets, retuning or post-filtering."},
        "validation":{"tactics":prior["validation"]["tactics"],"policy":"Required build/native rules/protocol/bench, exact Python/C# inference, explicit initialization and batch checks, common held-out diagnostics and frozen tactical thresholds. No fit-only promotion."},
        "matches":{**prior["matches"],"bootstrap_seed":20261125,
            "openings":{**prior["matches"]["openings"],"seed":20261124,
                "partition":"160 new parent pairs; first64 classical30ms,next64 H64control30ms,last32 conditional classical100ms. Exclude all old/current data, all prior parents including deep-turn, and tactical fixtures; freeze before candidate queries."}},
        "cost_diagnostic":{"positions":64,"rounds":9,"warmup_rounds":3,"repetitions_per_round":300,
            "policy":"Separate original BCL-only harness linked to the frozen runtime. Identical frozen legal make/eval/undo/eval operations for classical,H64,H128 in seeded counterbalanced order. Check root restoration and repeatable score checksums. Preserve raw timings and harness source/binary. Descriptive cost, not a strength or promotion gate; do not contend with matches or training."},
        "maximum_match_games":320,"rating":prior["rating"],
        "limits":"Same finite-label and endgame-biased source and historical static/deep mix. More capacity may worsen search cost; matched epoch count is not equal training compute. Extra units start zero-output, so initial function matches but optimization geometry differs. Teacher fit, timing and tactical gains do not establish Stockfish superiority."}
    path = ROOT / "artifacts/research/capacity-plan-v1.json"; write_new(path,plan)
    print(json.dumps({"declared":True,"plan_sha256":digest(path),"maximum_games":320}),flush=True)


if __name__ == "__main__": main()
