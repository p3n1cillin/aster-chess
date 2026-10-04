"""Independently check pair-stream isolation, zero weight and numerical gradients."""
import copy
import json

import torch

from run_rating import write_new
from train_network import PositionNetwork, objective, pair_partitions
from uci_client import ROOT


def main():
    base = "4k3/8/8/8/8/8/P7/4K3 w - - 0 1"
    rows = []
    for group,placement,start,fresh in ((10,"P7","w",False),(20,"1P6","b",False),(30,"2P5","w",True),(40,"3P4","w",True)):
        fen = base.replace("P7",placement).replace(" w ",f" {start} ")
        fields = fen.split(); fields[1] = "b" if start == "w" else "w"
        rows += [{"fen":fen,"game":group},{"fen":" ".join(fields),"game":group,"counterfactual_turn":True,"source_fen":fen}]
        if fresh: rows[-1]["fresh_deep_pair"] = True
    expected = {"old_training":[(0,1)],"old_validation":[(3,2)],"fresh_training":[(4,5)],"fresh_validation":[(6,7)]}
    assert pair_partitions(rows,{20,40}) == expected
    cases = 1
    for kind in ("parent_marker","string_marker","wrong_group","changed_fen","duplicate_counter"):
        bad = copy.deepcopy(rows)
        if kind == "parent_marker": bad[4]["fresh_deep_pair"] = True
        elif kind == "string_marker": bad[5]["fresh_deep_pair"] = "true"
        elif kind == "wrong_group": bad[5]["game"] = 40
        elif kind == "changed_fen": bad[5]["fen"] = bad[5]["fen"].replace("0 1","1 1")
        else: bad.append(copy.deepcopy(bad[5]))
        try: pair_partitions(bad,{20,40})
        except ValueError: pass
        else: raise AssertionError("Accepted invalid fresh pair: "+kind)
        cases += 1
    torch.manual_seed(43)
    model = PositionNetwork(8,classical_base=True,king_context=True,turn_output=True,phase_output=True,transformer_std=.1).double()
    with torch.no_grad():
        model.output[8:16].copy_(model.output[:8]); model.output[24:32].copy_(model.output[16:24])
    white = torch.tensor([[48,324],[48,324]]); black = torch.tensor([[432,708],[432,708]])
    turn = torch.tensor([1.,-1.],dtype=torch.float64); tempo = .12*turn; phase = torch.zeros(2,dtype=torch.float64)
    def loss(weight=None):
        scores = model(white,black,tempo,turn,phase)
        difference = (scores[0]-scores[1]).reshape(1)
        old = objective(difference,torch.tensor([.2],dtype=torch.float64))
        return old if weight is None else old+weight*objective(difference,torch.tensor([.9],dtype=torch.float64))
    loss().backward(); baseline = [parameter.grad.clone() for parameter in model.parameters()]
    model.zero_grad(set_to_none=True); loss(0.).backward()
    assert all(torch.equal(gradient,parameter.grad) for gradient,parameter in zip(baseline,model.parameters()))
    model.zero_grad(set_to_none=True); loss(1.).backward()
    assert any(not torch.equal(gradient,parameter.grad) for gradient,parameter in zip(baseline,model.parameters()))
    checked = 0
    for parameter,index in ((model.output,(16,)),(model.transformer.weight,(48,0))):
        analytic = parameter.grad[index].item()
        with torch.no_grad():
            original = parameter[index].item(); epsilon = 1e-6
            parameter[index] = original+epsilon; plus = loss(1.).item()
            parameter[index] = original-epsilon; minus = loss(1.).item()
            parameter[index] = original
        numeric = (plus-minus)/(2*epsilon)
        assert abs(analytic)>1e-8 and abs(analytic-numeric)<1e-8,(analytic,numeric)
        checked += 1
    report = {"passed":True,"partition_malformed_cases":cases,"zero_weight_gradients_exact":True,"fresh_weight_changes_gradients":True,
        "independent_finite_difference_checks":checked,"scope":"Old/fresh train/heldout pair isolation and weighted endgame-head/transformer gradients, without engine or model-selection queries."}
    write_new(ROOT / "artifacts/validation/deep-turn-pair-tests-v1.json",report)
    print(json.dumps(report))


if __name__ == "__main__": main()
