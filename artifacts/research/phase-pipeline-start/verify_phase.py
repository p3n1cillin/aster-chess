"""Check phase initialization, all legacy formats and independent integer inference."""
import argparse
import json
import os
import pathlib
import struct
import subprocess
import sys

import numpy as np
import torch

from neural_format import CONTEXT_FEATURES, FEATURES
from run_rating import digest, write_new
from train_network import PositionNetwork
from uci_client import DEFAULT_ENGINE, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default=str(DEFAULT_ENGINE))
    args = parser.parse_args()
    directory = ROOT / "artifacts/validation/phase-format-v1"
    directory.mkdir(exist_ok=False)
    torch.set_num_threads(1)
    networks, states = [], []
    for enabled in (False, True):
        torch.manual_seed(20261014)
        networks.append(PositionNetwork(64, True, True, .5, True, False, .1, enabled))
        states.append(torch.get_rng_state())
    control, phase = networks
    assert torch.equal(states[0], states[1])
    for name in ("linear.weight", "transformer.weight", "bias"):
        assert torch.equal(control.state_dict()[name], phase.state_dict()[name])
    assert torch.equal(control.output, phase.output[:128]) and torch.equal(control.output, phase.output[128:])
    white = torch.randint(0, CONTEXT_FEATURES, (50, 64)); black = torch.randint(0, CONTEXT_FEATURES, (50, 64))
    tempo = torch.linspace(-1, 1, 50); turn = torch.where(torch.arange(50) % 2 == 0, 1., -1.)
    phases = torch.arange(50) % 25
    torch.testing.assert_close(control(white, black, tempo, turn), phase(white, black, tempo, turn, phases), rtol=0, atol=1e-6)
    for kwargs in ({"turn_output": False}, {"squared_activation": True}, {"king_context": False}):
        options = dict(hidden=8, king_context=True, turn_output=True, phase_output=True); options.update(kwargs)
        try: PositionNetwork(**options)
        except ValueError: pass
        else: raise AssertionError("Invalid phase training flags accepted")
    rng = np.random.default_rng(20261112)
    reports = []
    for version in range(1, 12):
        # Version11 is a second version10 case with maximum legal hidden size
        # and signed-int16 output endpoints, requiring int64 phase blending.
        actual_version = min(version, 10)
        context, turn_output, phase_output = actual_version >= 3, actual_version >= 5, actual_version >= 9
        hidden = 256 if version == 11 else 16
        features = CONTEXT_FEATURES if context else FEATURES
        outputs = hidden * (4 if phase_output else 2 if turn_output else 1)
        linear = rng.integers(-200, 201, features, dtype=np.int16)
        bias = rng.integers(0, 257, hidden, dtype=np.int16)
        weights = rng.integers(-40, 41, (features, hidden), dtype=np.int16)
        output = rng.integers(-30000, 30001, outputs, dtype=np.int16)
        if version == 11:
            linear.fill(0); bias.fill(256); weights.fill(0)
            output[:2*hidden].fill(-32768); output[2*hidden:].fill(32767)
        model = directory / f"format-{version}.ann"
        with model.open("xb") as file:
            file.write(struct.pack("<8s5i", b"ASTNN001", actual_version, features, hidden, 256, 256))
            for values in (linear, bias, weights, output): file.write(values.astype("<i2").tobytes())
        for scalar in ((False, True) if phase_output else (False,)):
            suffix = "scalar" if scalar else "vector"
            destination = directory / f"format-{version}-{suffix}.json"
            env = os.environ.copy()
            if scalar: env["DOTNET_EnableHWIntrinsic"] = "0"
            command = [sys.executable, str(ROOT / "scripts/verify_network.py"), str(model), "--engine", args.engine, "--output", str(destination)]
            result = subprocess.run(command, capture_output=True, text=True, env=env)
            if result.returncode: raise RuntimeError(result.stdout + result.stderr)
            report = json.loads(result.stdout); assert report["status"] == "passed"
            reports.append({"version": actual_version, "hidden": hidden, "scalar": scalar,
                "positions": report["exact_inference_positions"], "path": destination.relative_to(ROOT).as_posix(), "sha256": digest(destination)})
    report = {"passed": True, "engine_sha256": digest(args.engine), "script_sha256": digest(__file__),
        "identical_initial_shared_parameters_and_rng": True, "identical_initial_predictions_tolerance": 1e-6,
        "checks": reports, "exact_inference_positions": sum(r["positions"] for r in reports),
        "interpretation": "Independent Python integer rebuild vs incremental C# inference. All existing formats preserved; phase formats additionally force scalar execution and test extreme int16 outputs. Not playing-strength evidence."}
    write_new(ROOT / "artifacts/validation/phase-formats.json", report)
    print(json.dumps({"passed": True, "exact_inference_positions": report["exact_inference_positions"], "formats": 10}))


if __name__ == "__main__": main()
