"""Validate explicit relation initialization and gradients of the new rows."""
import copy
import json
import pathlib
import tempfile

import chess
import torch

from neural_format import CONTEXT_FEATURES, feature_indices, material_phase
from run_rating import digest, read, write_new
from train_network import PositionNetwork, load_initial_checkpoint, objective
from uci_client import ROOT


def main():
    bundle = read(ROOT / "artifacts/research/relations-training-data-v1.json")
    path = ROOT / bundle["outputs"]["candidate"]["initial_checkpoint"]
    raw = torch.load(path,weights_only=True)
    def model(): return PositionNetwork(64,True,True,.5,True,False,.1,True,True)
    candidate = model(); load_initial_checkpoint(candidate,str(path))
    assert torch.equal(torch.get_rng_state(),raw["training_rng_state"])
    cases = 1
    with tempfile.TemporaryDirectory() as temporary:
        for kind in ("architecture","missing_parameter","shape","nan","bound","padding","rng"):
            bad = copy.deepcopy(raw)
            if kind == "architecture": bad["architecture"]["attack_features"] = False
            elif kind == "missing_parameter": del bad["state_dict"]["bias"]
            elif kind == "shape": bad["state_dict"]["output"] = bad["state_dict"]["output"][:-1]
            elif kind == "nan": bad["state_dict"]["bias"][0] = float("nan")
            elif kind == "bound": bad["state_dict"]["output"][0] = 2
            elif kind == "padding": bad["state_dict"]["transformer.weight"][-1,0] = .1
            else: bad["training_rng_state"] = torch.zeros(1,dtype=torch.uint8)
            destination = pathlib.Path(temporary)/"bad.pt"; torch.save(bad,destination)
            try: load_initial_checkpoint(model(),str(destination))
            except ValueError: pass
            else: raise AssertionError("Accepted invalid checkpoint: "+kind)
            cases += 1
    control = PositionNetwork(64,True,True,.5,True,False,.1,True)
    load_initial_checkpoint(control,str(ROOT / bundle["outputs"]["control"]["initial_checkpoint"]))
    assert torch.equal(candidate.linear.weight[:CONTEXT_FEATURES],control.linear.weight[:CONTEXT_FEATURES])
    assert torch.equal(candidate.transformer.weight[:CONTEXT_FEATURES],control.transformer.weight[:CONTEXT_FEATURES])
    assert torch.equal(candidate.bias,control.bias) and torch.equal(candidate.output,control.output)
    assert candidate.linear.weight[CONTEXT_FEATURES:].count_nonzero() == candidate.transformer.weight[CONTEXT_FEATURES:].count_nonzero() == 0
    candidate = candidate.double()
    board = chess.Board("4k3/4n3/8/3P4/8/8/8/K3R3 w - - 0 1")
    white = torch.tensor([feature_indices(board,chess.WHITE,True,True)])
    black = torch.tensor([feature_indices(board,chess.BLACK,True,True)])
    turn = torch.tensor([1.],dtype=torch.float64); phase = torch.tensor([material_phase(board)],dtype=torch.float64); tempo = torch.zeros(1,dtype=torch.float64)
    def loss(): return objective(candidate(white,black,tempo,turn,phase),torch.tensor([1.],dtype=torch.float64))
    loss().backward()
    checks = []
    for parameter in (candidate.linear.weight,candidate.transformer.weight):
        region = parameter.grad[CONTEXT_FEATURES:-1]
        flat = region.abs().argmax().item(); row,column = divmod(flat,region.shape[1]); row += CONTEXT_FEATURES
        analytic = parameter.grad[row,column].item()
        with torch.no_grad():
            epsilon = 1e-6; parameter[row,column] = epsilon; plus = loss().item()
            parameter[row,column] = -epsilon; minus = loss().item(); parameter[row,column] = 0
        numeric = (plus-minus)/(2*epsilon)
        assert abs(analytic)>1e-8 and abs(analytic-numeric)<1e-8,(analytic,numeric)
        checks.append({"feature":row,"column":column,"analytic":analytic,"numeric":numeric})
    result = {"passed":True,"script_sha256":digest(__file__),"checkpoint_validation_cases":cases,
        "shared_rows_bias_and_four_heads_exact":True,"extra_rows_initially_zero":True,"new_feature_gradient_numeric_checks":checks,
        "all_rows_initial_function_error_cp":bundle["initial_function_max_error_cp"]}
    write_new(ROOT / "artifacts/validation/relations-initial-tests-v1.json",result)
    print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
