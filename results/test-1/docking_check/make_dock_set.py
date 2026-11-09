import csv, json, random, urllib.request
from pathlib import Path
from rdkit import Chem
def chem_smiles(c):
    d = json.load(urllib.request.urlopen(f"https://data.rcsb.org/rest/v1/core/chemcomp/{c}", timeout=60))
    x = d["rcsb_chem_comp_descriptor"]; return x.get("SMILES_stereo") or x["SMILES"]
hub = list(csv.DictReader(open("/Users/tomato/Developer/GitHub/HTB26-Main/data/wholecell/releases/liu2023_hub20200324_chembl-37/tables/hub_pool.tsv"), delimiter="\t"))
by = {n: r for r in hub for n in r["names"].split(";")}
liu = {r["inchikey"] for r in csv.DictReader(open("/Users/tomato/Developer/GitHub/HTB26-Main/data/wholecell/releases/liu2023_hub20200324_chembl-37/tables/liu_train.tsv"), delimiter="\t")}
mols = []
for code, name in (("BB2", "actinonin (6JF3)"), ("LHY", "N-hydroxyurea fragment (6JF8)"), ("K1U", "K1U (6JF4)"), ("K2U", "K2U (6JF5)"), ("K3U", "K3U (6JF7)")):
    mols.append({"name": name, "group": "known PDF ligand", "smiles": chem_smiles(code)})
for n, label in (("RS-102895", "abaucin"), ("SU3327", "halicin"), ("delafloxacin", "delafloxacin"), ("epothilone-B", "epothilone-B")):
    mols.append({"name": label, "group": "hidden compound", "smiles": by[n]["smiles"]})
lib = [r for r in hub if r["inchikey"] not in liu and Chem.MolFromSmiles(r["smiles"]) and 10 <= Chem.MolFromSmiles(r["smiles"]).GetNumHeavyAtoms() <= 50
       and not any(n in by_names for n in r["names"].split(";") for by_names in [{"RS-102895","SU3327","delafloxacin","epothilone-B"}])]
random.Random(0).shuffle(lib)
for r in lib[:30]:
    mols.append({"name": r["names"].split(";")[0][:30], "group": "random library decoy", "smiles": r["smiles"]})
for m in mols: m["heavy_atoms"] = Chem.MolFromSmiles(m["smiles"]).GetNumHeavyAtoms()
Path("/private/tmp/claude-501/-Users-tomato-Developer-GitHub-HTB26-Main/c75775ad-f8dc-4d46-9c27-f0a39ed8b31c/scratchpad/pdf_scratch/molecules.json").write_text(json.dumps(mols, indent=1))
print(len(mols), "molecules:", {g: sum(m["group"] == g for m in mols) for g in {m["group"] for m in mols}})
