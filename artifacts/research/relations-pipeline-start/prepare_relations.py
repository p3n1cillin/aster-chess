"""Freeze H64 relation initialization with zero extra embeddings and common RNG."""
import hashlib
import json
import shutil

import chess
import torch

from neural_format import CONTEXT_FEATURES, RELATION_FEATURES, feature_indices, material_phase
from relations_plan import load_plan
from run_rating import digest, read, write_new
from train_network import PositionNetwork, load_initial_checkpoint
from uci_client import ROOT


def state_digest(model):
    checksum = hashlib.sha256()
    for tensor in model.state_dict().values(): checksum.update(tensor.detach().numpy().tobytes())
    return checksum.hexdigest()


def main():
    plan_path = ROOT / "artifacts/research/relations-plan-v1.json"; plan = load_plan(); setup = plan["training"]
    assert digest(ROOT / plan["data"]) == plan["data_sha256"] and digest(ROOT / plan["split_path"]) == plan["split_sha256"]
    assert digest(ROOT / setup["initial_control"]) == setup["initial_control_sha256"]
    directory = ROOT / "artifacts/research/relations-initial-v1"; directory.mkdir(exist_ok=False)
    torch.set_num_threads(setup["threads"]); torch.use_deterministic_algorithms(True)
    control = PositionNetwork(64,True,True,.5,True,False,.1,True)
    load_initial_checkpoint(control,str(ROOT / setup["initial_control"]))
    training_rng = torch.get_rng_state().clone()
    candidate = PositionNetwork(64,True,True,.5,True,False,.1,True,True)
    with torch.no_grad():
        candidate.linear.weight.zero_(); candidate.transformer.weight.zero_()
        candidate.linear.weight[:CONTEXT_FEATURES].copy_(control.linear.weight[:CONTEXT_FEATURES])
        candidate.transformer.weight[:CONTEXT_FEATURES].copy_(control.transformer.weight[:CONTEXT_FEATURES])
        candidate.bias.copy_(control.bias); candidate.output.copy_(control.output)
    outputs = {}
    for role,model in (("control",control),("candidate",candidate)):
        path = directory / (role+".pt")
        if role == "control": shutil.copy2(ROOT / setup["initial_control"],path)
        else:
            architecture = {"hidden":64,"classical_base":True,"king_context":True,"turn_output":True,"phase_output":True,"squared_activation":False,"attack_features":True}
            torch.save({"schema":1,"kind":"aster_initial_state","architecture":architecture,"state_dict":model.state_dict(),"training_rng_state":training_rng},path)
        provenance = load_initial_checkpoint(model,str(path))
        outputs[role] = {"initial_checkpoint":path.relative_to(ROOT).as_posix(),"sha256":provenance["sha256"],
            "initial_state_sha256":state_digest(model),"output":f"artifacts/training/relations-{role}-v1"}
    prior = read(ROOT / "artifacts/training/capacity-control-v1/training.json")
    assert state_digest(control) == prior["initial_state_sha256"]
    assert hashlib.sha256(training_rng.numpy().tobytes()).hexdigest() == prior["initial_rng_sha256"]
    rows = [json.loads(line) for line in (ROOT / plan["data"]).read_text().splitlines() if line.strip()]
    maximum = 0.; checked = 0
    with torch.no_grad():
        for start in range(0,len(rows),512):
            batch = rows[start:start+512]; boards = [chess.Board(row["fen"]) for row in batch]
            arrays = []
            for attack in (False,True):
                features,active = (RELATION_FEATURES,84) if attack else (CONTEXT_FEATURES,64)
                white = torch.full((len(batch),active),features,dtype=torch.long); black = torch.full_like(white,features)
                for i,board in enumerate(boards):
                    fw,fb = feature_indices(board,chess.WHITE,True,attack),feature_indices(board,chess.BLACK,True,attack)
                    white[i,:len(fw)] = torch.tensor(fw); black[i,:len(fb)] = torch.tensor(fb)
                arrays.append((white,black))
            turn = torch.tensor([1. if board.turn else -1. for board in boards]); phase = torch.tensor([material_phase(board) for board in boards],dtype=torch.float32)
            tempo = torch.tensor([row["classical_white_cp"]/100 for row in batch])
            a = control(*arrays[0],tempo,turn,phase); b = candidate(*arrays[1],tempo,turn,phase)
            maximum = max(maximum,float((a-b).abs().max())*100); checked += len(batch)
    assert checked == 63826 and maximum <= .001,(checked,maximum)
    result = {"schema":1,"complete":True,"plan_sha256":digest(plan_path),"preparer_sha256":digest(__file__),
        "data":plan["data"],"data_sha256":plan["data_sha256"],"split_path":plan["split_path"],"split_sha256":plan["split_sha256"],
        "classical_provenance_sha256":digest(ROOT / (plan["data"]+".classical.json")),"positions":checked,
        "initial_function_max_error_cp":maximum,"common_training_rng_sha256":hashlib.sha256(training_rng.numpy().tobytes()).hexdigest(),"outputs":outputs}
    write_new(ROOT / "artifacts/research/relations-training-data-v1.json",result)
    print(json.dumps(result),flush=True)


if __name__ == "__main__": main()
