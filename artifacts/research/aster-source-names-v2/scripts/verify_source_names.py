"""Audit editable source names; attribution, configuration and evidence are separate data."""
import argparse
import json
from pathlib import Path
import re

from research_reference import research_text

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("crates", "scripts", "src", "tests", ".github")
SOURCE_EXTENSIONS = {".rs", ".py", ".cs", ".ps1", ".yml", ".yaml", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".sh", ".bat", ".cmd"}


def audit(root=ROOT):
    forbidden = re.compile(research_text("forbidden_identity_pattern"), re.IGNORECASE)
    files = []
    hits = []
    for directory in SOURCE_ROOTS:
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or path.suffix not in SOURCE_EXTENSIONS:
                continue
            relative = path.relative_to(root).as_posix()
            if any(part in {"target", "__pycache__", ".venv"} for part in path.relative_to(root).parts):
                continue
            files.append(relative)
            if forbidden.search(relative):
                hits.append({"path": relative, "line": None, "kind": "filename"})
            for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                if forbidden.search(line):
                    hits.append({"path": relative, "line": number, "kind": "source"})
    return {"passed": not hits, "files_scanned": len(files), "roots": SOURCE_ROOTS,
            "extensions": sorted(SOURCE_EXTENSIONS), "hits": hits,
            "scope": "Editable source and filenames only. Original notices (.license), package attribution, JSON metadata, documents, datasets, archived evidence and Git history retain factual names."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit()
    if args.output:
        path = Path(args.output)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
