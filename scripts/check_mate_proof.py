"""Verify the general-proof candidate while checking unchanged playing behavior."""
import json
import subprocess
import sys

from match import frozen_source_manifest
from run_rating import digest, read, write_new
from uci_client import ROOT, UciClient


def main():
    plan_path = ROOT / "artifacts/research/mate-proof-plan-v1.json"; plan = read(plan_path)
    engine = ROOT / "artifacts/publish/mate-proof-dev-v2/Aster.dll"
    source = ROOT / "artifacts/research/mate-proof-source-v2/manifest.json"
    if (ROOT / "artifacts/validation/mate-proof-preflight.json").exists(): raise ValueError("Preserve previous preflight")
    frozen_source_manifest(str(source), digest(engine))
    for entry in read(source)["source_files"]: assert digest(ROOT / entry["path"]) == entry["sha256"]
    assert "55 passed, 0 failed." in (ROOT / "artifacts/validation/mate-proof-tests-v2.txt").read_text()
    general = read(ROOT / "artifacts/validation/mate-proof-general-v2.json")
    assert general["passed"] and general["engine_sha256"] == digest(engine)
    assert len(general["legacy_certificates"]) == 36 and len(general["differential_cases"]) == 64
    for role in ("parent", "match"): assert read(ROOT / f"artifacts/validation/mate-proof-{role}-audit.json")["passed"]
    playing_files = [entry for entry in read(ROOT / plan["baseline_source"])["source_files"]
        if entry["path"].startswith("src/Engine/") and entry["path"].endswith(".cs") and entry["path"].split("/")[-1] not in ("EndgameProof.cs", "Program.cs", "Uci.cs")]
    for entry in playing_files: assert digest(ROOT / entry["path"]) == entry["sha256"], entry["path"]
    def run(name, command):
        path = ROOT / f"artifacts/validation/mate-proof-{name}.txt"
        with path.open("x", encoding="utf-8") as log: subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    run("rules-v2", [sys.executable, str(ROOT / "scripts/verify.py"), "--setups", "1000", "--engine", str(engine),
        "--output", str(ROOT / "artifacts/validation/mate-proof-rules-v2.json")])
    run("bench7-v2", ["dotnet", str(engine), "bench", "7"])
    last = (ROOT / "artifacts/validation/mate-proof-bench7-v2.txt").read_text().splitlines()[-1]
    assert json.loads(last)["totalNodes"] == 146772
    tactics = {}
    for name, suite, limit, minimum in (("original-depth8", "tactics-v1.json", ["--depth", "8"], 32),
            ("original-nodes", "tactics-v1.json", ["--nodes", "5000"], 32),
            ("quiet-depth8", "tactics-quiet-v1.json", ["--depth", "8"], 32),
            ("quiet-nodes", "tactics-quiet-v1.json", ["--nodes", "5000"], 25),
            ("endgames-nodes", "endgames-v1.json", ["--nodes", "5000"], 13)):
        output = ROOT / f"artifacts/tactics/mate-proof-{name}.json"
        run(name, [sys.executable, str(ROOT / "scripts/tactics.py"), str(ROOT / "tests/fixtures" / suite), "--engine", str(engine),
            *limit, "--require-solved", str(minimum), "--output", str(output)])
        tactics[name] = read(output)["solved"]
    output = ROOT / "artifacts/benchmarks/mate-proof-default-vs-phase-depth8.json"
    run("default-comparison", [sys.executable, str(ROOT / "scripts/compare_search.py"), "--engine", str(engine), "--opponent", str(ROOT / plan["baseline"]),
        "--suite", str(ROOT / "tests/fixtures/mate-proof-parent-v1.json"), "--depth", "8", "--output", str(output)])
    comparison = read(output)
    assert all(r["same_move"] and r["same_score"] and r["candidate"]["nodes"] == r["opponent"]["nodes"] for r in comparison["positions"])
    sf = read(ROOT / "tools/stockfish/manifest.json"); assert digest(ROOT / sf["executable"]) == sf["executable_sha256"]
    with UciClient(ROOT / sf["executable"]) as client:
        client.send("explain mate 3"); client.send("isready"); transcript = client.until("readyok")
        assert not any(line.startswith("info string explanation ") for line in transcript)
    write_new(ROOT / "artifacts/validation/mate-proof-preflight.json", {"passed": True, "candidate": engine.relative_to(ROOT).as_posix(),
        "candidate_sha256": digest(engine), "candidate_source": source.relative_to(ROOT).as_posix(), "candidate_source_sha256": digest(source),
        "plan_sha256": digest(plan_path), "general_verification_sha256": digest(ROOT / "artifacts/validation/mate-proof-general-v2.json"),
        "unchanged_playing_files": playing_files, "behavior": comparison["summary"], "tactics": tactics,
        "native_stockfish_reference": {"manifest": sf, "responses": transcript},
        "candidate_revision": "Additional invalid-root triple-check rejection, expanded terminal clock/legacy tests, before matches. Original binary/source/diagnostics retained. No valid-position proof algorithm, playing code or declared gate changes.",
        "interpretation": "New native general certificate interface passes independent strategy/protocol checks. Pinned Stockfish does not natively return this explanation command; external tools can add such functionality. Exact normal playing outputs retained, not a strength improvement claim."})
    print(json.dumps({"passed": True, "behavior": comparison["summary"], "tactics": tactics}))


if __name__ == "__main__": main()
