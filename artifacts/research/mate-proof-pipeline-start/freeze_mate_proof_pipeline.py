"""Freeze complete general-proof correctness evidence and scripts before matches."""
import datetime
import json
import shutil

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    preflight = read(ROOT / "artifacts/validation/mate-proof-preflight.json"); assert preflight["passed"]
    directory = ROOT / "artifacts/research/mate-proof-pipeline-start"; directory.mkdir(exist_ok=False)
    scripts = []
    for name in ("declare_mate_proof.py", "prepare_mate_proof.py", "verify_general_proofs.py", "verify_mate_proof.py", "verify_strategy_proof.py",
            "check_mate_proof.py", "run_mate_proof.py", "preserve_mate_proof.py", "freeze_mate_proof_pipeline.py", "match.py", "audit_match.py",
            "run_rating.py", "uci_client.py", "verify.py", "tactics.py", "compare_search.py", "generate_openings.py", "audit_openings.py", "freeze_engine_source.py"):
        shutil.copy2(ROOT / "scripts" / name, directory / name)
        scripts.append({"path": name, "sha256": digest(directory / name)})
    evidence = []
    for folder in ("artifacts/validation", "artifacts/benchmarks", "artifacts/tactics", "tests/fixtures"):
        for path in sorted((ROOT / folder).glob("mate-proof-*.json")):
            evidence.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)})
    write_new(directory / "manifest.json", {"created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256": digest(ROOT / "artifacts/research/mate-proof-plan-v1.json"), "source_files": scripts, "evidence": evidence,
        "candidate_sha256": preflight["candidate_sha256"], "candidate_source_sha256": preflight["candidate_source_sha256"],
        "interpretation": "Frozen before fixed32-game unchanged-play regression. Certificate capability verified separately. No adaptive extension or strength inference."})
    print(json.dumps({"scripts": len(scripts), "evidence": len(evidence), "manifest_sha256": digest(directory / "manifest.json")}))


if __name__ == "__main__": main()
