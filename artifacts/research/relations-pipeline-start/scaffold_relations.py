"""One-shot derivation of the matched experiment's orchestration from capacity."""
from uci_client import ROOT


def main():
    names = ["train_capacity.py","prepare_capacity_openings.py","prepare_capacity_cost.py","run_capacity_cost.py",
        "report_capacity_fit.py","check_capacity.py","freeze_capacity_pipeline.py","run_capacity.py","assess_capacity.py",
        "audit_capacity_match_metadata.py","report_capacity_initial_search.py","audit_capacity_cost.py","preserve_capacity.py"]
    for name in names:
        text = (ROOT / "scripts" / name).read_text().replace("capacity","relations").replace("Capacity","Relations")
        text = text.replace("from uci_client import ROOT","from uci_client import ROOT\nfrom relations_plan import load_plan")
        text = text.replace('plan = read(plan_path)','plan = load_plan()')
        text = text.replace('plan = read(ROOT / "artifacts/research/relations-plan-v1.json")','plan = load_plan()')
        if name == "train_capacity.py":
            text = text.replace('str(setup["fresh_pair_loss_weight"])]','str(setup["fresh_pair_loss_weight"])]\n            if role == "candidate": command += ["--attack-features"]')
            text = text.replace("then nested H128", "then H64 relation features")
        elif name == "prepare_capacity_openings.py":
            text = text.replace('str(ROOT / "tests/fixtures/deep-turn-parent-v1.json")]',
                'str(ROOT / "tests/fixtures/deep-turn-parent-v1.json"),"--exclude-suite",str(ROOT / "tests/fixtures/capacity-parent-v1.json")]')
        elif name == "prepare_capacity_cost.py": text = text.replace("random.Random(20261123)", 'random.Random(setup["order_seed"])')
        elif name in ("run_capacity_cost.py","audit_capacity_cost.py"):
            text = text.replace("NeuralCost","RelationCost")
        elif name == "check_capacity.py":
            text = text.replace('rebuilt = read(ROOT / "artifacts/research/relations-rebuild-source/manifest.json")', 'rebuilt = read(ROOT / plan["baseline_source"])')
            text = text.replace('"55 passed, 0 failed."','"57 passed, 0 failed."')
            text = text.replace('Training-only objective ablation on unchanged runtime','Geometric relation feature ablation on a shared runtime')
        elif name == "freeze_capacity_pipeline.py":
            text = text.replace('"declare_relations.py","prepare_relations.py"','"relations_plan.py","verify_relations.py","scaffold_relations.py","declare_relations.py","prepare_relations.py"')
            text = text.replace('"record_relations_session.py",','')
        elif name == "assess_capacity.py": text = text.replace("nested hidden-relations ablation","geometric relation feature ablation")
        target = ROOT / "scripts" / name.replace("capacity","relations")
        with target.open("x",encoding="utf-8") as stream: stream.write(text)
    folder = ROOT / "tools/RelationCost"; folder.mkdir(exist_ok=False)
    (folder / "Program.cs").write_text((ROOT / "tools/NeuralCost/Program.cs").read_text().replace("NeuralCost","RelationCost"),encoding="utf-8")
    (folder / "RelationCost.csproj").write_text((ROOT / "tools/NeuralCost/NeuralCost.csproj").read_text().replace("NeuralCost","RelationCost").replace("mate-proof-dev-v2","relations-dev"),encoding="utf-8")


if __name__ == "__main__": main()
