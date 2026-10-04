"""Freeze nested initial states and check their initial function on every row."""
import hashlib
import json

import chess
import torch

from neural_format import CONTEXT_FEATURES, FEATURES, feature_indices, material_phase
from run_rating import digest, read, write_new
from train_network import PositionNetwork, load_initial_checkpoint
from uci_client import ROOT


def state_digest(model):
    checksum = hashlib.sha256()
    for tensor in model.state_dict().values(): checksum.update(tensor.detach().numpy().tobytes())
    return checksum.hexdigest()


def main():
    plan_path = ROOT / "artifacts/research/capacity-plan-v1.json"; plan = read(plan_path); setup = plan["training"]
    assert digest(ROOT / plan["data"]) == plan["data_sha256"] and digest(ROOT / plan["split_path"]) == plan["split_sha256"]
    directory = ROOT / "artifacts/research/capacity-initial-v1"; directory.mkdir(exist_ok=False)
    torch.set_num_threads(setup["threads"]); torch.use_deterministic_algorithms(True); torch.manual_seed(setup["seed"])
    def create(hidden):
        return PositionNetwork(hidden,setup["classical_base"],setup["king_context"],setup["activation_bias"],setup["turn_output"],
            setup["squared_activation"],setup["transformer_std"],setup["phase_output"])
    control = create(64); training_rng = torch.get_rng_state().clone(); candidate = create(128)
    extra_rng = torch.Generator().manual_seed(setup["extra_initial_seed"])
    with torch.no_grad():
        candidate.linear.weight.copy_(control.linear.weight)
        candidate.transformer.weight[:,:64].copy_(control.transformer.weight)
        candidate.transformer.weight[:,64:].zero_()
        candidate.transformer.weight[:FEATURES,64:].copy_(torch.randn((FEATURES,64),generator=extra_rng)*setup["transformer_std"])
        candidate.bias[:64].copy_(control.bias); candidate.bias[64:].fill_(setup["activation_bias"])
        candidate.output.zero_()
        for head in range(4): candidate.output[128*head:128*head+64].copy_(control.output[64*head:64*(head+1)])
    prior = read(ROOT / "artifacts/training/deep-turn-control-v1/training.json")
    assert state_digest(control) == prior["initial_state_sha256"]
    assert hashlib.sha256(training_rng.numpy().tobytes()).hexdigest() == prior["initial_rng_sha256"]
    outputs = {}
    for role,model in (("control",control),("candidate",candidate)):
        path = directory / (role+".pt")
        architecture = {"hidden":model.bias.numel(),**{key:setup[key] for key in ("classical_base","king_context","turn_output","phase_output","squared_activation")}}
        torch.save({"schema":1,"kind":"aster_initial_state","architecture":architecture,"state_dict":model.state_dict(),"training_rng_state":training_rng},path)
        provenance = load_initial_checkpoint(model,str(path))
        outputs[role] = {"initial_checkpoint":path.relative_to(ROOT).as_posix(),"sha256":provenance["sha256"],"initial_state_sha256":state_digest(model),
            "output":f"artifacts/training/capacity-{role}-v1"}
    rows = [json.loads(line) for line in (ROOT / plan["data"]).read_text().splitlines() if line.strip()]
    maximum = 0.; checked = 0
    with torch.no_grad():
        for start in range(0,len(rows),512):
            batch = rows[start:start+512]; boards = [chess.Board(row["fen"]) for row in batch]
            white = torch.full((len(batch),64),CONTEXT_FEATURES,dtype=torch.long); black = torch.full_like(white,CONTEXT_FEATURES)
            for i,board in enumerate(boards):
                fw,fb = feature_indices(board,chess.WHITE,True),feature_indices(board,chess.BLACK,True)
                white[i,:len(fw)] = torch.tensor(fw); black[i,:len(fb)] = torch.tensor(fb)
            turn = torch.tensor([1. if board.turn else -1. for board in boards]); phase = torch.tensor([material_phase(board) for board in boards],dtype=torch.float32)
            tempo = torch.tensor([row["classical_white_cp"]/100 for row in batch])
            a = control(white,black,tempo,turn,phase); b = candidate(white,black,tempo,turn,phase)
            maximum = max(maximum,float((a-b).abs().max())*100); checked += len(batch)
    assert checked == 63826 and maximum <= .0001,(checked,maximum)
    write_new(ROOT / "artifacts/research/capacity-training-data-v1.json",{"schema":1,"complete":True,"plan_sha256":digest(plan_path),
        "preparer_sha256":digest(__file__),"data":plan["data"],"data_sha256":plan["data_sha256"],"split_path":plan["split_path"],
        "split_sha256":plan["split_sha256"],"classical_provenance_sha256":digest(ROOT / (plan["data"]+".classical.json")),"positions":checked,
        "initial_function_max_error_cp":maximum,"common_training_rng_sha256":hashlib.sha256(training_rng.numpy().tobytes()).hexdigest(),"outputs":outputs})
    print(json.dumps({"prepared":True,"positions":checked,"initial_function_max_error_cp":maximum,"outputs":outputs}),flush=True)


if __name__ == "__main__": main()
