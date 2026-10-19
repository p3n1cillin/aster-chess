"""Declare geometric relation features before implementation or initialization."""
from research_reference import research_text
import json

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    prior_path = ROOT / "artifacts/research/capacity-plan-v1.json"
    prior = read(prior_path)
    assert not read(ROOT / "artifacts/research/capacity-decision-v1.json")["eligible_for_promotion"]
    plan = {**prior, "status":"Declared before relation implementation, initialization, training or new opening/candidate queries",
        "hypothesis":"Add 80 compact geometric attack/defense features to H64, testing useful piece relationships rather than increased hidden width. The control uses the same new runtime with unchanged format9; the candidate uses format11.",
        "prior_experiment":"artifacts/research/capacity-experiment-v1-manifest.json",
        "prior_experiment_sha256":digest(ROOT / "artifacts/research/capacity-experiment-v1-manifest.json"),
        "frozen_classical_reference": {key:prior[key] for key in ("baseline","baseline_sha256","baseline_source")},
        "runtime_policy":"Freeze new runtime/source after required checks, before training matches. All candidate/control/classical match roles use that exact runtime. Compare classical depth8 moves/scores/nodes and bench against the prior runtime; playing search/evaluation/rules stay unchanged except optional neural feature inference.",
        "features":{"ordinary_context_features":13056,"extra_features":80,"maximum_active_features":84,
            "categories":"absolute color White then Black, piece kind pawn/knight/bishop/rook/queen, status undefended then defended; 20 categories",
            "semantics":"Geometric opponent attack intersected with each piece bitboard; undefended excludes own geometric control, defended intersects own control. Both colors' maps include pawn, knight, bishop, rook, queen and king attacks; sliders include the first occupied square. Pins count geometrically; this is not legal capture, SEE, a hanging-piece proof or zugzwang. No side-to-move or en-passant pseudo-target dependence.",
            "encoding":"Count each category and clip to0..3, where3 means3+. One-hot4bins per category. Perspective-relative color: own first, opponent second. Index13056+(((relativeColor*5+kind)*2+status)*4+bin). Twenty active features per perspective, including count0 bins.",
            "formats":"11 hybrid and12 standalone, clipped phase/turn/king-context mandatory; formats1..10 preserved",
            "incremental":"Rebuild maps only when geometry changed; update categorical embeddings by removing prior bins and adding new bins. King-bucket rebuilds must restore relation embeddings even when counts stay unchanged. Null move preserves geometry; speculative make/undo without evaluation cancels deltas.",
            "verification":"Independent python-chess geometric maps vs native bitboards on broad legal positions, malformed model checks, exact nonzero quantized inference, make/eval/undo, null moves, king buckets, phase changes, castling, promotion, en-passant and pinned pieces."},
        "training":{**prior["training"],"control_hidden":64,"candidate_hidden":64,
            "initialization":"Load the frozen capacity H64 initial checkpoint and embed its first13056 rows unchanged in candidate H64; new80 linear/transformer rows and padding row zero. Bias and all4 output blocks unchanged. Restore same post-H64 Torch RNG before batch shuffles. Check all63826 initial predictions within0.001cp; differing feature-array lengths can change float summation order. Record maximum actual error, never select using labels.",
            "initial_control":"artifacts/research/capacity-initial-v1/control.pt",
            "initial_control_sha256":digest(ROOT / "artifacts/research/capacity-initial-v1/control.pt"),
            "control_reproduction":"Reproduce capacity/deep-turn H64 model byte for byte, epoch9, initial full state/RNG and all50 batch hashes; stop before candidate if it fails.",
            "selection":"Same63826 rows, whole-game6050 validation, H64 width, 50epochs, objective old-pair1/fresh-pair0 and batch orders; ordinary held-out loss alone selects epochs. Candidate adds only80 relation features; no retuning or post-filtering."},
        "matches":{**prior["matches"],"bootstrap_seed":20261128,
            "openings":{**prior["matches"]["openings"],"seed":20261127,
                "partition":"160 fresh parent pairs: first64 classical30ms,next64 matched H64control30ms,last32 conditional classical100ms. Exclude all old/current training, diagnostics, tactical fixtures and prior opening parents including capacity; freeze before candidate queries."}},
        "cost_diagnostic":{**prior["cost_diagnostic"],"order_seed":20261126,
            "policy":"New BCL-only RelationCost harness, frozen new runtime, same64 held-out roots and legal children, 9 counterbalanced rounds,3warmups,300repeats. Independently verify every role's checksum and root restoration. No contention with training/matches; timing is descriptive only."},
        "limits":research_text('declare_relations.interpretation')}
    plan.pop("baseline"); plan.pop("baseline_sha256"); plan.pop("baseline_source")
    plan["training"].pop("extra_initial_seed",None)
    path = ROOT / "artifacts/research/relations-plan-v1.json"
    write_new(path,plan)
    print(json.dumps({"declared":True,"sha256":digest(path),"maximum_games":plan["maximum_match_games"]}),flush=True)


if __name__ == "__main__": main()
