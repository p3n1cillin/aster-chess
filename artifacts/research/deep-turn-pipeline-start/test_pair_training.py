"""Check paired data isolation and the extra objective's gradient numerically."""
import copy
import json

import torch

from train_network import PositionNetwork, objective, turn_pairs


def main():
    fen = "4k3/8/8/8/8/8/P7/4K3 w - - 0 1"
    other = fen.replace(" w ", " b ")
    rows = [{"fen": fen, "game": 10},
            {"fen": other, "source_fen": fen, "game": 10, "counterfactual_turn": True},
            {"fen": other.replace("P7", "1P6"), "game": 20},
            {"fen": fen.replace("P7", "1P6"), "source_fen": other.replace("P7", "1P6"),
             "game": 20, "counterfactual_turn": True}]
    assert turn_pairs(rows, {20}) == ([(0, 1)], [(3, 2)])
    for change in ("game", "fen", "source_fen", "duplicate"):
        bad = copy.deepcopy(rows)
        if change == "game": bad[1]["game"] = 20
        elif change == "fen": bad[1]["fen"] = other.replace("P7", "2P5")
        elif change == "source_fen": bad[1]["source_fen"] = "missing"
        else: bad.append(copy.deepcopy(bad[1]))
        try:
            turn_pairs(bad, {20})
        except ValueError:
            pass
        else:
            raise AssertionError("Accepted invalid pair: " + change)
    torch.manual_seed(42)
    model = PositionNetwork(8, classical_base=True, turn_output=True, transformer_std=.1).double()
    with torch.no_grad():
        # Initial antisymmetric heads cancel transformer gradients in a turn
        # difference; use asymmetric heads to check the learned regime too.
        model.output[8:].copy_(model.output[:8])
    white = torch.tensor([[48, 324], [48, 324]])
    black = torch.tensor([[432, 708], [432, 708]])
    turn = torch.tensor([1., -1.], dtype=torch.float64)
    tempo = .12 * turn
    target = torch.tensor([.9], dtype=torch.float64)

    def loss():
        scores = model(white, black, tempo, turn)
        return objective((scores[0] - scores[1]).reshape(1), target)

    loss().backward()
    # Independently perturb an output coefficient and a sparse transformer
    # coefficient: both halves of the paired computation must differentiate.
    for parameter, index in ((model.output, (0,)), (model.transformer.weight, (48, 0))):
        gradient = parameter.grad[index].item()
        with torch.no_grad():
            original = parameter[index].item()
            epsilon = 1e-6
            parameter[index] = original + epsilon
            plus = loss().item()
            parameter[index] = original - epsilon
            minus = loss().item()
            parameter[index] = original
        numeric = (plus - minus) / (2 * epsilon)
        assert abs(gradient) > 1e-8
        assert abs(gradient - numeric) < 1e-8, (gradient, numeric)
    print(json.dumps({"passed": True, "partition_and_malformed_checks": 5,
                      "independent_finite_difference_checks": 2}))


if __name__ == "__main__":
    main()
