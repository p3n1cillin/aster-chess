"""Check explicit checkpoint validation and nested zero-output gradient behavior."""
import copy
import json
import pathlib
import tempfile

import torch

from run_rating import read, write_new
from train_network import PositionNetwork, load_initial_checkpoint, objective
from uci_client import ROOT


def main():
    bundle = read(ROOT / "artifacts/research/capacity-training-data-v1.json")
    path = ROOT / bundle["outputs"]["candidate"]["initial_checkpoint"]
    raw = torch.load(path,weights_only=True)
    def model(): return PositionNetwork(128,True,True,.5,True,False,.1,True)
    candidate = model(); load_initial_checkpoint(candidate,str(path))
    assert torch.equal(torch.get_rng_state(),raw["training_rng_state"])
    cases = 1
    with tempfile.TemporaryDirectory() as temporary:
        for kind in ("architecture","missing_parameter","shape","nan","bound","padding","rng"):
            bad = copy.deepcopy(raw)
            if kind == "architecture": bad["architecture"]["hidden"] = 64
            elif kind == "missing_parameter": del bad["state_dict"]["bias"]
            elif kind == "shape": bad["state_dict"]["output"] = bad["state_dict"]["output"][:-1]
            elif kind == "nan": bad["state_dict"]["bias"][0] = float("nan")
            elif kind == "bound": bad["state_dict"]["output"][0] = 2
            elif kind == "padding": bad["state_dict"]["transformer.weight"][-1,0] = .1
            else: bad["training_rng_state"] = torch.zeros(1,dtype=torch.uint8)
            destination = pathlib.Path(temporary)/"bad.pt"; torch.save(bad,destination)
            try: load_initial_checkpoint(model(),str(destination))
            except ValueError: pass
            else: raise AssertionError("Accepted invalid initial checkpoint: "+kind)
            cases += 1
    control = PositionNetwork(64,True,True,.5,True,False,.1,True)
    load_initial_checkpoint(control,str(ROOT / bundle["outputs"]["control"]["initial_checkpoint"]))
    assert torch.equal(candidate.linear.weight,control.linear.weight)
    assert torch.equal(candidate.transformer.weight[:,:64],control.transformer.weight)
    assert candidate.transformer.weight[-1].count_nonzero() == 0
    for head in range(4):
        assert torch.equal(candidate.output[head*128:head*128+64],control.output[head*64:(head+1)*64])
        assert candidate.output[head*128+64:(head+1)*128].count_nonzero() == 0
    candidate = candidate.double()
    white = torch.tensor([[48,324],[48,324]]); black = torch.tensor([[432,708],[432,708]])
    turn = torch.tensor([1.,-1.],dtype=torch.float64); phase = torch.zeros(2,dtype=torch.float64); tempo = .12*turn
    def loss():
        return objective(candidate(white,black,tempo,turn,phase),torch.tensor([1.,-.4],dtype=torch.float64))
    loss().backward()
    index = 2*128+64; analytic = candidate.output.grad[index].item()
    with torch.no_grad():
        epsilon = 1e-6; candidate.output[index] = epsilon; plus = loss().item()
        candidate.output[index] = -epsilon; minus = loss().item(); candidate.output[index] = 0
    numeric = (plus-minus)/(2*epsilon)
    assert abs(analytic)>1e-8 and abs(analytic-numeric)<1e-8,(analytic,numeric)
    result = {"passed":True,"checkpoint_validation_cases":cases,"shared_columns_and_four_heads_exact":True,
        "extra_output_initially_zero":True,"extra_output_gradient_numeric_check":True,"all_rows_initial_function_error_cp":bundle["initial_function_max_error_cp"]}
    write_new(ROOT / "artifacts/validation/capacity-initial-tests-v1.json",result); print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
