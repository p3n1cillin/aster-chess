"""Confirm prior experiment archives remain byte-identical after new research."""
import json
import pathlib
import shutil

from run_rating import digest, read, write_new
from uci_client import ROOT


def main():
    checked = []
    for name in ("capacity","deep-turn"):
        path = ROOT / f"artifacts/research/{name}-experiment-v1-manifest.json"
        manifest = read(path)
        for entry in manifest["artifacts"]:
            assert digest(ROOT / entry["path"]) == entry["sha256"],entry["path"]
        checked.append({"experiment":name,"manifest":path.relative_to(ROOT).as_posix(),
            "manifest_sha256":digest(path),"archived_artifacts":len(manifest["artifacts"])})
    source = ROOT / "artifacts/research/relations-prior-archive-audit-source-v1"; source.mkdir(exist_ok=False)
    shutil.copy2(__file__,source / pathlib.Path(__file__).name)
    result = {"passed":True,"script_sha256":digest(__file__),"prior_experiments":checked,
        "scope":"Archived artifacts only. Root training helpers intentionally changed for the new feature format; old archived copies retain their exact hashes."}
    write_new(ROOT / "artifacts/validation/relations-prior-archive-audit-v1.json",result)
    print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
