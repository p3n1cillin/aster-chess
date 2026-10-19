"""Freeze the balanced stable-label endgame training ablation before generation."""
from research_reference import research_text
import json

from run_rating import digest, write_new
from uci_client import ROOT


def main():
    old_data = "artifacts/data/teacher-turn-60k-static-v1-classical.jsonl"
    baseline = "artifacts/publish/mate-proof-dev-v2/Aster.dll"
    plan = {"schema": 1, "status": "declared before fresh data, labels, training or candidate queries",
        "hypothesis": "Stable deeper search labels on fresh balanced endgames improve actual search compared with static labels on identical positions. Same architecture/data/groups/init/optimizer/batches/objective/budget; only4096 fresh target values differ.",
        "baseline": baseline, "baseline_sha256": digest(ROOT / baseline), "baseline_source": "artifacts/research/mate-proof-source-v2/manifest.json",
        "old_data": old_data, "old_data_sha256": digest(ROOT / old_data),
        "generation": {"positions": 4096, "score_ranges_abs_cp": [[0,150],[151,400],[401,800],[801,1500]], "quota_each": 1024,
            "games": 8192, "max_plies": 320, "per_game": 8, "minimum_ply": 40, "sample_every": 4, "maximum_phase": 8, "maximum_pieces": 12,
            "maximum_halfmove_clock": 59, "play_nodes": 512, "random_probability": .03, "seed": 20261116,
            "sample_nodes": 16384, "verify_nodes": 65536, "label_multipv": 1,
            "acceptance": "Fresh canonical position, no check/terminal/claimable draw; finite scores at both budgets, abs(verified)<=1500, first PV move identical and white cp difference<=50, bucket quota available. No selection by Aster evaluator errors/moves. Preserve every queried candidate, native mate labels, rejection reasons, histories and source outcome; source results are descriptive, unresolved kept separate.",
            "history": "Labels from fresh FEN with clock, no played repetition history. Full source histories/PGNs retained separately. Teacher player uses its own512-node process and game token; labeler clears between FEN queries.",
            "exclude_data": [old_data, "artifacts/data/teacher-20k-v1.jsonl", "artifacts/data/endgame-diagnostic-512-v1.jsonl"],
            "exclude_suites": [*[f"tests/fixtures/openings-v{i}.json" for i in range(1,6)],
                *[f"tests/fixtures/{n}-parent-v1.json" for n in ("rating","lazy-order","q-evasion","iir","phase","mate-proof")],
                "tests/fixtures/tactics-v1.json", "tests/fixtures/tactics-quiet-v1.json", "tests/fixtures/endgames-v1.json"]},
        "training": {"control": "Old60000 unchanged plus4096 fresh rows with teacher static labels", "candidate": "Same64096 rows, only fresh labels use verified stable search score",
            "hidden": 64, "epochs": 50, "batch_size": 512, "learning_rate": .0002, "threads": 4, "seed": 20261014,
            "classical_base": True, "king_context": True, "turn_output": True, "phase_output": True, "squared_activation": False,
            "activation_bias": .5, "transformer_std": .1, "pair_loss_weight": 1.,
            "split": "Retain all269 original held-out games from phase-output-v1; fresh source IDs offset100000. Select10% of fresh games using Random20261117, freeze split before training. Both models use exact same full split and initial/RNG states. Select each epoch only by its ordinary mixed held-out loss; report both models on common held-out deep/static targets and per-phase metrics, never select by matches.",
            "classical_scores": "Frozen ordinary0.7.9 ac907eac evaluator, FEN-only; preserve binary/source and hashes"},
        "validation": "Audit every source PGN/history/result, canonical uniqueness/exclusions, acceptance/quota and native label/PV types; re-query64 seeded accepted labels at both budgets and32 accepted at262144 nodes diagnostically (no post-filtering). Build/test/rules/protocol/bench, exact quantized inference and all original/quiet/endgame tactical thresholds. Preserve incomplete artifacts if generation budget fails; never restart from state JSON.",
        "matches": {"short_pairs_each": 64, "seconds_per_move": .03, "opponents": ["frozen classical0.7.9", "matched fresh-static model"],
            "conditional_long_pairs": 32, "long_seconds_per_move": .1, "resources": {"Threads":1,"Hash":64,"Move Overhead":0,"max_additional_plies":400},
            "bootstrap_samples":20000,"bootstrap_seed":20261119,
            "gate": "Always finish both128-game short screens. Longer64-game classical confirmation only if correctness and tactics pass, zero forfeits/unresolved, classical short family95% lower strictly>50% and control point>=50% with lower>=45%. Promotion additionally needs long point>=50%, family lower>=45%, zero forfeits/unresolved. No adaptive extension or retuning.",
            "openings": {"positions":160,"attempts":2048,"seed":20261118,"plies":20,"nodes":2048,"verify_nodes":20000,"max_cp":80,
                "partition":"first64 pairs vs classical30ms,next64 vs static30ms,last32 conditional classical100ms; exclude old+fresh training data and every earlier parent suite. Freeze before Aster queries."}},
        "maximum_match_games":320,"rating":"No new calibration in this data screen. Retain exact earlier0.7.6-q-evasion local2319 interval2277..2360; new models do not inherit it.",
        "no_adaptive_extension":True,"limits":research_text('declare_stable_endgames.interpretation')}
    write_new(ROOT / "artifacts/research/stable-endgame-plan-v1.json", plan)
    print(json.dumps({"declared":True,"plan_sha256":digest(ROOT / "artifacts/research/stable-endgame-plan-v1.json"),"fresh_positions":4096,"maximum_games":320}))


if __name__ == "__main__": main()
