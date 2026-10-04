"""Freeze runner, analyzer, inputs and completed diagnostics before IIR matches."""
import datetime
import json
import shutil

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    directory = ROOT / "artifacts/research/iir-pipeline-start"
    if directory.exists(): raise ValueError("Preserve previous pipeline snapshot")
    plan_path = ROOT / "artifacts/research/iir-plan-v2.json"
    plan = read(plan_path)
    assert digest(ROOT / plan["previous_plan"]["path"]) == plan["previous_plan"]["sha256"]
    assert "52 passed, 0 failed." in (ROOT / "artifacts/validation/iir-engine-tests.txt").read_text(encoding="utf-8-sig")
    assert "51 passed, 0 failed." in (ROOT / "artifacts/validation/iir-default-engine-tests.txt").read_text(encoding="utf-8-sig")
    for role in ("candidate","baseline"): assert digest(ROOT / plan[role]) == plan[role + "_sha256"]
    assert read(ROOT / "artifacts/validation/iir-rules.json")["status"] == "passed"
    assert read(ROOT / "artifacts/validation/iir-differential.json")["cases"] == 256
    comparison = read(ROOT / "artifacts/benchmarks/iir-default-vs-baseline-depth8.json")
    assert all(r["same_move"] and r["same_score"] and r["candidate"]["nodes"] == r["opponent"]["nodes"] for r in comparison["positions"])
    directory.mkdir()
    names = ("match.py","audit_match.py","run_iir.py","assess_iir.py","analyze_iir_rating.py","verify_iir.py",
        "declare_iir.py","prepare_iir.py","generate_openings.py","audit_openings.py","analyze_rating.py","run_rating.py",
        "uci_client.py","verify.py","verify_q_evasion.py","tactics.py","compare_search.py","freeze_engine_source.py","freeze_iir_pipeline.py")
    entries = []
    for name in names:
        shutil.copy2(ROOT / "scripts" / name,directory / name)
        entries.append({"path":name,"sha256":digest(directory / name)})
    evidence = []
    for folder in ("artifacts/validation","artifacts/benchmarks","artifacts/tactics","tests/fixtures"):
        for path in sorted((ROOT / folder).glob("iir-*.json")):
            evidence.append({"path":path.relative_to(ROOT).as_posix(),"sha256":digest(path)})
    for name in ("docs/INTERNAL-REDUCTIONS.md","docs/VERSION-CONTROL.md","README.md","ROADMAP.md","AGENTS.md","artifacts/PROGRESS.md"):
        shutil.copy2(ROOT / name,directory / name.split("/")[-1])
    write_new(directory / "manifest.json",{"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "plan_sha256":digest(plan_path),"source_files":entries,"evidence":evidence,
        "interpretation":"Frozen before regression matches, including conditional rating analyzer. No adaptive extension or retuning."})
    print(json.dumps({"scripts":len(entries),"evidence":len(evidence),"manifest_sha256":digest(directory / "manifest.json")}))


if __name__ == "__main__": main()
