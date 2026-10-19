"""Declare fresh deep-turn pair supervision before counterfactual labels or training."""
from research_reference import research_text
import json

from run_rating import digest, write_new
from uci_client import ROOT


def main():
    old = "artifacts/data/teacher-turn-60k-static-v1-classical.jsonl"
    parents = "artifacts/data/stable-endgame-4096-v1.jsonl"
    baseline = "artifacts/publish/mate-proof-dev-v2/Aster.dll"
    plan = {"schema":1,"status":"Declared before opposite-turn teacher queries, dataset construction, training or candidate match queries",
        "hypothesis":"On identical two-sided deep-labelled endgames, fresh paired-turn loss improves search versus ordinary supervision plus the unchanged old static pair loss. Only the additional fresh-pair objective differs between models.",
        "old_data":old,"old_data_sha256":digest(ROOT / old),"parents":parents,"parents_sha256":digest(ROOT / parents),
        "parent_audit":"artifacts/validation/stable-endgame-data-audit-v1.json","parent_audit_sha256":digest(ROOT / "artifacts/validation/stable-endgame-data-audit-v1.json"),
        "prior_split":"artifacts/research/stable-endgame-split-v1.json","prior_split_sha256":digest(ROOT / "artifacts/research/stable-endgame-split-v1.json"),
        "baseline":baseline,"baseline_sha256":digest(ROOT / baseline),"baseline_source":"artifacts/research/mate-proof-source-v2/manifest.json",
        "generation":{"maximum_parents":4096,"sample_nodes":16384,"verify_nodes":65536,"multipv":1,
            "selection":"Visit every frozen White parent once in original file order. Flip only side to move. Reject invalid raw EP/structural/terminal/check roots and canonical collisions with excluded data/suites. Query every eligible Black root at both budgets, preserving native mate labels. Accept only finite scores, abs(verified)<=1500, same first PV move and <=50cp change. No student errors/moves or pair-delta thresholds select data.",
            "minimum_pairs":512,"minimum_training_pairs":256,"minimum_heldout_pairs":32,
            "history":"Counterfactual Black FEN has no played history or observed outcome. Retain actual White source histories/results and original PGN fingerprints separately. Both labels use cold FEN-only search. No raw EP/clock/castling fields are changed to make a pair eligible.",
            "data_policy":"Keep old60000 byte-identical; append both White and Black only for eligible pairs. White targets import frozen verified labels, Black targets use new verified labels. Fresh additions have equal side counts, without promising equal score bins after pairing. Preserve all4096 prechecks/queries, exclusions, rejected labels and source provenance; no extra parents or adaptive quota relaxation.",
            "exclude_counter_data":[old,"artifacts/data/teacher-20k-v1.jsonl","artifacts/data/endgame-diagnostic-512-v1.jsonl",parents],
            "exclude_counter_suites":[*[f"tests/fixtures/openings-v{i}.json" for i in range(1,6)],
                *[f"tests/fixtures/{name}-parent-v1.json" for name in ("rating","lazy-order","q-evasion","iir","phase","mate-proof","stable-endgame")],
                "tests/fixtures/tactics-v1.json","tests/fixtures/tactics-quiet-v1.json","tests/fixtures/endgames-v1.json"]},
        "training":{"hidden":64,"epochs":50,"batch_size":512,"learning_rate":.0002,"threads":4,"seed":20261014,
            "classical_base":True,"king_context":True,"turn_output":True,"phase_output":True,"squared_activation":False,
            "activation_bias":.5,"transformer_std":.1,"pair_loss_weight":1.,"control_fresh_pair_loss_weight":0.,"candidate_fresh_pair_loss_weight":1.,
            "split":"Preserve all269 original validation groups; eligible fresh groups inherit their already-frozen stable-endgame train/validation assignment. Drop absent groups from the split file, never move a present held-out group to training. Freeze exact rows and split before training.",
            "batching":"Separate old and fresh pair streams. Both models shuffle and evaluate fresh training batches even at zero weight, consuming identical RNG. Same complete initial state, ordinary/old-pair/fresh-pair orders and budget. Old objective remains weight1; fresh objective is weight0 versus1. Held-out pairs never enter optimization.",
            "selection":"Select each epoch solely by the same ordinary held-out target loss. Pair diagnostics, tactics and matches never select or retune weights."},
        "validation":{"requery_pairs":64,"requery_seed":20261120,"deeper_pairs":32,"deeper_nodes":262144,
            "policy":"Audit every parent/counter history relation, FEN field, collision, acceptance and label/PV type; recheck every paired classical score,64 pairs at both teacher budgets and32 pairs deeper diagnostically, without post-filtering. Verify old/fresh pair isolation and gradients independently, fixed split/init/batch equality, required build/native rules/protocol/bench, exact Python/C# inference and all tactical thresholds.",
            "tactics":{"tactics-depth8":32,"tactics-5000nodes":32,"tactics-quiet-depth8":32,"tactics-quiet-5000nodes":25,"endgames-5000nodes":13}},
        "matches":{"short_pairs_each":64,"seconds_per_move":.03,"conditional_long_pairs":32,"long_seconds_per_move":.1,
            "resources":{"Threads":1,"Hash":64,"Move Overhead":0,"max_additional_plies":400},
            "bootstrap_samples":20000,"bootstrap_seed":20261122,
            "gate":"Always finish both128-game short screens. Long64-game classical confirmation only with correctness/tactics,zero forfeits/unresolved,classical short95% family lower>50%,control point>=50% and family lower>=45%. Promotion additionally long point>=50%,family lower>=45%,zero issues. No extension/retuning.",
            "openings":{"positions":160,"attempts":2048,"seed":20261121,"plies":20,"nodes":2048,"verify_nodes":20000,"max_cp":80,
                "partition":"first64 classical30ms,next64 matched control30ms,last32 conditional classical100ms; exclude old/current/fresh paired training and all prior parents; freeze before candidate queries."}},
        "maximum_match_games":320,"rating":"No new calibration; last exact0.7.6-q-evasion estimate2319,local95%2277..2360 retained. Models do not inherit it.",
        "limits":research_text('declare_deep_turn.interpretation')}
    path = ROOT / "artifacts/research/deep-turn-plan-v1.json"; write_new(path,plan)
    print(json.dumps({"declared":True,"plan_sha256":digest(path),"maximum_counter_queries":4096,"maximum_match_games":320}))


if __name__ == "__main__": main()
