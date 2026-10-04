"""Retain the exact prior rating after a completed non-calibration ablation."""
import datetime
import json
import shutil

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    decision_path = ROOT / "artifacts/research/deep-turn-decision-v1.json"; decision = read(decision_path)
    state = read(ROOT / "artifacts/research/deep-turn-match-execution-v1.json")
    assert state["status"] == "complete"
    reference_path = ROOT / "artifacts/ratings/session-20261004-q-evasion-confirmation.json"; reference = read(reference_path)
    prior = read(ROOT / "artifacts/ratings/session-20261004-stable-endgame.json")
    assert digest(reference_path) == prior["reference_record"]["sha256"]
    assert reference["numeric_local_rating"] == prior["last_measured_local_rating"]
    assert reference["primary_95_percent_local_interval"] == prior["primary_95_percent_local_interval"]
    assert digest(ROOT / prior["rated_engine"]) == prior["rated_engine_sha256"]
    preflight = read(ROOT / "artifacts/validation/deep-turn-preflight.json")
    plan_path = ROOT / "artifacts/research/deep-turn-plan-v1.json"
    report = {key:prior[key] for key in ("public_elo","last_measured_local_rating","primary_95_percent_local_interval","local_scale",
        "rated_engine","rated_engine_sha256","rated_version","reference_record")}
    report.update(schema=1,timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status="Prior exact calibrated reference retained; deep-turn models receive no rating from regression screens",
        plan={"path":plan_path.relative_to(ROOT).as_posix(),"sha256":digest(plan_path)},
        runtime_binary_sha256=preflight["engine_sha256"],
        model_sha256={role:item["sha256"] for role,item in preflight["models"].items()},
        failed_gates=decision["failed_gates"],paired_screens=decision["results"],
        decision_sha256=digest(decision_path),recorder_sha256=digest(__file__),
        reason="This fixed-budget fresh paired-turn objective ablation is not a rating calibration. Neither model inherits the old exact binary's estimate. Public Elo and superiority to full-strength Stockfish remain unestablished.")
    # The canonical record is also retained verbatim inside this experiment's
    # preserved research tree, so its bytes join the final artifact manifest.
    output = ROOT / "artifacts/ratings/session-20261004-deep-turn.json"
    copy = ROOT / "artifacts/research/deep-turn-rating-reference-v1.json"
    source = ROOT / "artifacts/research/deep-turn-rating-source"
    if output.exists() or copy.exists() or source.exists(): raise ValueError("Preserve prior session records")
    write_new(output,report); write_new(copy,report)
    assert digest(output) == digest(copy)
    source.mkdir(); shutil.copy2(__file__,source / "record_deep_turn_session.py")
    print(json.dumps({"last_measured_local_rating":report["last_measured_local_rating"],"interval":report["primary_95_percent_local_interval"],
        "record_sha256":digest(output),"failed_gates":decision["failed_gates"]}),flush=True)


if __name__ == "__main__": main()
