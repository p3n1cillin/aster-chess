"""Recompute the frozen rating analysis without overwriting any saved evidence."""
import contextlib
import io
import json

import analyze_rating
from run_rating import digest, read
from uci_client import ROOT


def main():
    saved = read(ROOT / "artifacts/ratings/session-20261004-calibration-v1.json")
    if digest(analyze_rating.__file__) != saved["analyzer_sha256"]:
        raise ValueError("Use the exact preserved analyzer for this rating record")
    checked = []

    def compare_without_write(path, calculated):
        if str(path) != str(ROOT / "artifacts/ratings/session-20261004-calibration-v1.json"):
            raise ValueError("Unexpected analysis output")
        old = dict(saved); new = dict(calculated)
        old.pop("timestamp_utc"); new.pop("timestamp_utc")
        if old != new: raise ValueError("Saved rating differs from recomputed evidence")
        checked.append(True)

    original = analyze_rating.write_new
    try:
        analyze_rating.write_new = compare_without_write
        with contextlib.redirect_stdout(io.StringIO()): analyze_rating.main()
    finally:
        analyze_rating.write_new = original
    if checked != [True]: raise ValueError("Analyzer did not produce exactly one verified result")
    print(json.dumps({"status": "passed", "saved_rating_unchanged": True,
                      "numeric_local_rating": saved["numeric_local_rating"],
                      "primary_95_percent_local_interval": saved["primary_95_percent_local_interval"],
                      "all_games_audited": saved["all_games_audited"], "verifier_sha256": digest(__file__)}))


if __name__ == "__main__": main()
