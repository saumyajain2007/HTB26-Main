# Build reference

**Reference only. Design decisions lived in `plan.md`, which was removed on 26 Oct 2026 and stays in the Git history; this file has none.** It keeps recipes checked live on 24 Oct 2026 against Open Targets 26.09, ChEMBL 37 and RCSB:
- account setup;
- Open Targets, ChEMBL and PubChem queries;
- the approval and bioactivity rules;
- docking.

IDs follow `plan.md` section 3, and terms follow [`glossary.md`](../method/glossary.md). The research behind these recipes is in `docs/research/planning/`.

## 1. Account setup

### Snowflake (stream A)

Done when one REST call returns text.

1. Sign up through the MLH student trial link (`mlh.link/snowflake-signup`).
2. In a worksheet, run:

   ```sql
   SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;
   -- If the value is not ANY_REGION (needs the ACCOUNTADMIN role):
   ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';
   SELECT AI_COMPLETE('claude-sonnet-5', 'Reply with the single word OK');
   ```

3. Create a programmatic access token (PAT) as described in the MLH tutorial repo `annafil/cortex-rest-api-demo`, including its network-policy step. Ignore the tutorial's endpoint and model name, which are out of date.
4. Test the REST endpoint:

   ```bash
   curl -s "https://$SNOWFLAKE_ACCOUNT.snowflakecomputing.com/api/v2/cortex/v1/chat/completions" \
     -H "Authorization: Bearer $SNOWFLAKE_PAT" -H "Content-Type: application/json" \
     -d '{"model":"claude-sonnet-5","messages":[{"role":"user","content":"Reply with OK"}]}'
   ```

5. If AI functions are disabled, check Snowflake's trial-account docs: self-service trials need a payment card on the account before AI features work, and adding one does not end the trial. Decide as a team, ask the Snowflake mentor, or use the jury fallback in `plan.md` section 12.

### Tiger Cloud (stream C)

Done when `psql "$DATABASE_URL" -c 'select 1'` works.

1. Sign up through `mlh.link/tigerdata-quickstart` (trial with $1,000 credit, no card).
2. Create a service in `eu-west-2` (London). Save the downloaded config file: it is the only time the password is shown.
3. Create the tables listed in `plan.md` section 9.3.

### GitHub Codespaces (stream C)

Done when `curl https://<codespace name>-8000.app.github.dev/api/healthz` returns 200.

The demo codespace owner does this once:
1. Give `gh` the `codespace` scope: `gh auth refresh -h github.com -s codespace`, then approve the device code in the browser. It refreshes the active account, so run `gh auth switch -u Abudidayo` first if that is not the one. Where `GH_TOKEN` is set for another account (Conductor sets one), prefix both commands with `env -u GH_TOKEN`.
2. In GitHub → Settings → Codespaces:
   - add the secrets `DATABASE_URL`, `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_PAT`, available to `Abudidayo/ai-drug-discovery`;
   - set the default idle timeout to 240 minutes;
   - leave retention at the default (30 days).
3. Tiger Cloud: Codespaces has no fixed outgoing IP. Check that the service has no IP allow list, or allow all IPs for the event.
4. Create and check the codespace as in [`.devcontainer/README.md`](../../.devcontainer/README.md).

### Data cache (stream A)

About 127 MB in total:

```bash
mkdir -p data/ot && cd data/ot
for d in drug_molecule drug_mechanism_of_action drug_warning clinical_indication \
         clinical_target clinical_report disease target; do
  aws s3 sync --no-sign-request \
    "s3://open-targets-public-data-releases/platform/26.09/output/$d/" "$d/"
done
curl -O https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/chembl_uniprot_mapping.txt
```

Without the AWS CLI, download the same folders from `http://ftp.ebi.ac.uk/pub/databases/opentargets/platform/26.09/output/`. Inspect the columns before writing joins:

```bash
duckdb -c "DESCRIBE SELECT * FROM 'data/ot/clinical_indication/*.parquet'"
```

## 2. Open Targets, ChEMBL and PubChem recipes

All Open Targets calls go to `POST https://api.platform.opentargets.org/api/v4/graphql` with the body `{"query": ..., "variables": ...}`. Batch target and drug lookups (25 to 200 IDs per call): Open Targets asks users not to query one entity at a time. Cache every response in `evidence_cache`.

**A1. Resolve the disease.**

Use `search` for the picker:

```graphql
query SearchDisease($q: String!) {
  search(queryString: $q, entityNames: ["disease"], page: {index: 0, size: 10}) {
    total hits { id name entity description score } } }
```

Use `mapIds` for exact names:

```graphql
query MapIds($terms: [String!]!) {
  mapIds(queryTerms: $terms, entityNames: ["disease"]) {
    total mappings { term hits { id name entity score } } } }
```

- Always show the resolved ID and label. They can differ from what the user typed: "multiple myeloma" resolves to "plasma cell myeloma", and the partial term "covid" ranks long COVID first.
- When loading a saved experiment, check `disease(efoId: $id) { obsoleteTerms }` for retired IDs.

**A2. Fetch all associations.** Pages hold at most 3000 rows. Loop `index` until all `count` rows are fetched:

```graphql
query Assoc($id: String!, $i: Int!, $size: Int!) {
  disease(efoId: $id) {
    associatedTargets(page: {index: $i, size: $size}) {
      count
      rows { target { id approvedSymbol } score
             datatypeScores { id score } datasourceScores { id score } } } } }
```

**A3. Re-score client-side, in three modes.** Do not use the server-side `datasources` argument: it replaces the whole weight table instead of changing one weight.

```python
import math

NORM = math.pi ** 2 / 6
# Non-default Open Targets weights; every other datasource has weight 1.0.
DEFAULT_WEIGHTS = {"europepmc": 0.2, "expression_atlas": 0.2, "impc": 0.2,
                   "cancer_biomarkers": 0.5, "ot_crispr_validation": 0.5,
                   "ot_crispr": 0.5, "encore": 0.5}
DROP = {
    "default": set(),
    "evidence_only": {"clinical_precedence", "cancer_biomarkers"},
    "strict": {"clinical_precedence", "cancer_biomarkers", "europepmc"},
}

def target_score(datasource_scores, mode):
    weighted = [DEFAULT_WEIGHTS.get(d["id"], 1.0) * d["score"]
                for d in datasource_scores if d["id"] not in DROP[mode]]
    return sum(v / i ** 2 for i, v in enumerate(sorted(weighted, reverse=True), 1)) / NORM
```

- **Unit test:** in `default` mode, every row must match the API's `score` within 0.0001.
- `clinical_precedence` comes from trials of drugs in the disease. `cancer_biomarkers` rows can name the drug itself. `europepmc` is literature co-mentions.

**A4. Drugs already used or trialled for a disease.** Use these to find known answers for evaluation, and to keep trial labels out of ranking features (`plan.md` section 6.3):

```graphql
query DiseaseDrugs($id: String!) {
  disease(efoId: $id) {
    drugAndClinicalCandidates {
      count
      rows {
        id maxClinicalStage
        drug { id name drugType maximumClinicalStage parentMolecule { id name }
               mechanismsOfAction { rows { mechanismOfAction actionType targets { id approvedSymbol } } } }
        clinicalReports { id source clinicalStage trialOverallStatus trialStartDate url title } } } } }
```

- There is no pagination: the response can be about 3 MB, so cache it.
- `ClinicalReport.year` is null; use `trialStartDate`.

**A5. Drugs acting on given targets.** Fan out from a list of targets, 25 IDs per call:

```graphql
query TargetDrugs($ids: [String!]!) {
  targets(ensemblIds: $ids) {
    id approvedSymbol
    drugAndClinicalCandidates {
      count
      rows { id maxClinicalStage
             drug { id name drugType maximumClinicalStage parentMolecule { id name } }
             diseases { diseaseFromSource disease { id name } } } } } }
```

- Collapse salts and hydrates onto `drug.parentMolecule.id`, falling back to `drug.id`.
- One known bad edge: deuruxolitinib is parented to ruxolitinib, so show both names.
- `row.maxClinicalStage` is the stage for that target–drug pair; `drug.maximumClinicalStage` is the stage across all indications.

**A6. Check approval provenance.** Batch 25 drugs per call:

```graphql
query DrugApprovals($ids: [String!]!) {
  drugs(chemblIds: $ids) {
    id name drugType maximumClinicalStage
    indications { rows { maxClinicalStage disease { id name }
                         clinicalReports { source clinicalStage } } } } }
```

Keep a drug only if it has an indication row at `APPROVAL` whose reports include a source in {`FDA`, `EMA Human Drugs`, `PMDA`, `DailyMed`}. This removes never-approved drugs such as navitoclax, which Open Targets shows at `APPROVAL`. Store the matching sources as `approval_sources`.

**A7. Add bioactivity edges (small molecules only).** Open Targets mechanism data alone misses targets: for example, baricitinib's mechanism lists only JAK1 and JAK2, although it also potently inhibits TYK2. For each candidate:

```
GET https://www.ebi.ac.uk/chembl/api/data/activity.json?molecule_chembl_id={id}&pchembl_value__gte=5&target_organism=Homo%20sapiens&limit=1000&only=target_chembl_id,pchembl_value
```

- Group the activities by target and keep targets with a median pChEMBL of at least 7.
- **ChEMBL target to Ensembl gene ID** (`plan.md` section 3; never through gene symbols): call `/target.json?target_chembl_id__in={ids}`.
  - Keep only `target_type == "SINGLE PROTEIN"`.
  - Take the UniProt accession from `target_components[].accession`.
  - Map the accession to an Ensembl gene ID through Open Targets `target.proteinIds` entries whose source starts with `uniprot_`. If it matches no gene or several, mark the target `unmapped` with the reason.
- `limit` is capped at 1000, so follow `page_meta.next`. Cache results per drug.

**A8. Direct-evidence score (the baseline in `plan.md` section 6.1).** For each drug, take its targets (mechanism and bioactivity):

- `evidence_score` = the highest target score;
- `breadth` = the sum of target scores, used only to break ties.

Sort by `(evidence_score, breadth)`. The UI shows every supported target, with no other bonus for hitting more targets.

**A10. Build evidence items** for the UI and the jury. Number them `E1`, `E2`, … once per Experiment, so each ID is unique across all its candidates (`plan.md` section 3):

- **Target association:** symbol, mode score and datatype breakdown, linked to `https://platform.opentargets.org/evidence/{ensembl_id}/{disease_id}`.
- **Mechanism:** the `mechanismOfAction` sentence plus its references.
- **Bioactivity:** "median pChEMBL X across N human assays", linked to the ChEMBL compound page.
- **Safety:** the `drugWarnings` lines, or "No warnings recorded: safety unknown". Fetch adverse events lazily for the selected drug only, because they are slow:

  ```graphql
  query DrugSafety($id: String!) {
    drug(chemblId: $id) {
      id name drugWarnings { warningType toxicityClass country year references { id source url } }
      adverseEvents(page: {index: 0, size: 10}) { count criticalValue rows { name count logLR } } } }
  ```

  Adverse events are reporting signals (`logLR` against `criticalValue`), not incidence rates.
- **Trials for this disease:** show them as context in the UI, but keep them out of ranking features and jury packets (`plan.md` section 6.3).

**A11. Fetch structure images from PubChem.** Look drugs up by InChIKey from ChEMBL (`molecule_structures.standard_inchi_key`):

- `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/inchikey/{key}/cids/JSON` returns the CID.
- `/compound/cid/{cid}/PNG?image_size=400x400` returns the 2D drawing, usable directly as `<img src>`.
- Property responses use the keys `SMILES` and `ConnectivitySMILES`, not `CanonicalSMILES`.
- Antibodies have no CID: skip them and set `dockable: false`.

## 3. Docking recipes

**C1. Install.** The dev container already has this toolchain, pinned in `.devcontainer/docking-requirements.txt`. To install it on a Mac for local testing:

```bash
sudo apt-get update && sudo apt-get install -y python3-venv python3-pip git
python3 -m venv ~/dock && source ~/dock/bin/activate
pip install -U numpy scipy rdkit vina meeko gemmi posebusters
python -c "import vina, rdkit; print(vina.__version__, rdkit.__version__)"
```

If `pip install vina` fails to build, try either of these:
- conda-forge: `micromamba create -n dock -c conda-forge python=3.11 vina meeko rdkit gemmi prody`;
- the official `vina_1.2.7_linux_x86_64` or `vina_1.2.7_mac_aarch64` binary from the AutoDock-Vina GitHub releases.

Record the Vina, Meeko and RDKit versions; the UI shows them, because one RDKit version change halved a published docking benchmark result.

**C2. Prepare structures.** Start with these entries. All are non-covalent and verified on RCSB:

| PDB | Target | Co-crystal ligand (component ID) | Use |
|---|---|---|---|
| 6WTO | JAK2 kinase domain, 1.74 Å | baricitinib (`3JW`) | Redocking control; JAK-family candidates |
| 6WTN | JAK2 kinase domain, 1.83 Å | ruxolitinib (`RXT`) | Cross-docking control |
| 6O0K | BCL2, 1.62 Å | venetoclax (`LBM`) | Myeloma worked example |
| 7BQU | CRBN with SALL4, 1.9 Å | S-thalidomide (`EF2`) | Small and quick to dock |

Add two or three more from the evaluation and demo diseases. Each one needs:
- a human protein;
- an X-ray structure at 2.5 Å or better;
- one chain around the pocket;
- a non-covalent, drug-like co-crystal ligand;
- at least one approved small molecule acting on that target.

Find entries with the RCSB search below. It returns structures of a UniProt protein that have a bound ligand, sorted by resolution; RCSB returns HTTP 204 when nothing matches.

```json
{"query": {"type": "group", "logical_operator": "and", "nodes": [
  {"type": "terminal", "service": "text", "parameters": {
     "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
     "operator": "exact_match", "value": "<UniProt accession>"}},
  {"type": "terminal", "service": "text", "parameters": {
     "attribute": "rcsb_entry_info.nonpolymer_entity_count", "operator": "greater", "value": 0}}]},
 "return_type": "entry",
 "request_options": {"paginate": {"start": 0, "rows": 5}, "results_content_type": ["experimental"],
   "sort": [{"sort_by": "rcsb_entry_info.resolution_combined", "direction": "asc"}]}}
```

POST it to `https://search.rcsb.org/rcsbsearch/v2/query`.

Avoid the 20S proteasome (5LF3 and similar), XPO1, and any entry where the drug is bound covalently.

**C3. Prepare a receptor** with `app/worker/htb_worker/prepare.py`. Run it once per structure and commit the outputs to `app/worker/structures/{PDB}/`.

1. Download `https://files.rcsb.org/download/{PDB}.pdb`.
2. Keep the chosen chain. Remove waters, ions, all ligands and alternate conformations with gemmi.
3. Make every residue match a Meeko template. Meeko 0.8.0's `mk_prepare_receptor.py` refuses any residue with missing heavy atoms (`REMARK 470`; 6WTO has 34, 6WTN 25). Cut each such side chain back to the atoms the crystal has: alanine when CB is there, else glycine. Do not rebuild them: PDBFixer's rebuilt side chains had distorted geometry, so Meeko saw extra bonds and still refused them. A phosphorylated residue (PTR, SEP, TPO) loses its phosphate, and MSE becomes MET, only outside the box; inside it, refuse the structure. 6WTO's phosphotyrosines (PTR 1007-1008) lie more than 20 Å from the box centre, so they become TYR. Record every change in `meta.json`.
4. Write the receptor PDBQT with Meeko's `mk_prepare_receptor.py`. Follow the Vina "basic docking" tutorial for the flags that match the installed Meeko version (`mk_prepare_receptor.py --help`).
5. Download the crystal ligand pose from `https://models.rcsb.org/v1/{PDB}/ligand?label_comp_id={COMP}&encoding=sdf`. The box centre is the ligand's heavy-atom centroid; the box is a 25 Å cube.
6. Write `meta.json` containing `pdb_id`, `chain`, `uniprot`, `symbol`, `ligand_comp_id`, `box_center`, `box_size` and `control_smiles`.

**C4. Prepare a ligand.** Take the SMILES from ChEMBL (`molecule_structures.canonical_smiles`):

```python
from rdkit import Chem
from rdkit.Chem import AllChem

mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
AllChem.EmbedMolecule(mol, randomSeed=42)
AllChem.MMFFOptimizeMolecule(mol)
Chem.MolToMolFile(mol, "ligand.sdf")
```

Then run `mk_prepare_ligand.py -i ligand.sdf -o ligand.pdbqt`.

**C5. Dock** with `worker/dock.py`:

```python
from vina import Vina

v = Vina(sf_name="vina", seed=42)
v.set_receptor("receptor.pdbqt")
v.set_ligand_from_file("ligand.pdbqt")
v.compute_vina_maps(center=box_center, box_size=[25, 25, 25])
v.dock(exhaustiveness=8, n_poses=9)
v.write_poses("poses.pdbqt", n_poses=9, overwrite=True)
energies = v.energies(n_poses=9)  # column 0 is the total score per pose
```

- Convert poses to SDF with `mk_export.py poses.pdbqt -s poses.sdf`.
- Write `scores.json` and `log.txt` alongside.
- Runtime for baricitinib into 6WTO on the 4-core codespace (24 Oct 2026): 10.8 s at exhaustiveness 8, 21.9 s at 16 and 43.6 s at 32. All are well inside the 180-second job timeout. Pick the highest setting that still leaves room for receptor and ligand preparation.

**C6. Redocking control.** Ship it as a visible feature.

1. Dock the crystal ligand's SMILES into its own prepared structure, with the same box and settings as user jobs.
2. Compute the RMSD of the top pose to the crystal pose: symmetry-aware, heavy atoms, no realignment.

   ```python
   from rdkit import Chem
   from rdkit.Chem import AllChem, rdMolAlign

   ref = Chem.MolFromMolFile("crystal_ligand.sdf")
   ref = AllChem.AssignBondOrdersFromTemplate(Chem.MolFromSmiles(control_smiles), ref)
   pose = Chem.RemoveHs(next(Chem.SDMolSupplier("poses.sdf")))
   rmsd = rdMolAlign.CalcRMS(pose, Chem.RemoveHs(ref))  # success if rmsd <= 2.0
   ```

   Measured controls (25 Oct 2026, C3 preparation above, exhaustiveness 8, seed 42): 6O0K venetoclax 1.08 Å and 7BQU thalidomide 0.41 Å pass. 6WTO baricitinib 2.43 Å and 6WTN ruxolitinib 2.83 Å **fail the 2.0 Å threshold**: in both JAK2 top poses the pyrrolopyrimidine is turned, while a 1.4-1.6 Å pose ranks lower. Exhaustiveness 16 and 32 do not change it. Do not tune settings until the control passes; that would overfit the control.

3. Run PoseBusters: `bust poses.sdf -l crystal_ligand.sdf -p receptor.pdb`. Show pass or fail per check group.
4. **Negative control:** dock an unrelated approved drug into the same box. The viewer still draws a convincing-looking pose, which shows why a pose is not evidence.
5. The control card reads: "Redocking control: baricitinib into 6WTO, RMSD = X.X Å (success ≤ 2.0 Å), PoseBusters: PASS". Fill in real numbers only.

**C7. Job queue** (Postgres only, no broker).

1. `POST /api/dock` checks that the PDB is in the prepared set and the drug is `dockable`.
2. It computes `cache_key` = SHA-256 of (pdb_id, chain, canonical SMILES, box, engine, engine version, exhaustiveness, seed).
   - If a `done` job with that key exists, return it at once.
   - Otherwise insert a `queued` row and return `202 {job_id}`.
   - Allow at most 3 queued jobs per session.
3. The worker loop claims a job with:

   ```sql
   UPDATE dock_jobs SET status = 'running', started_at = now()
   WHERE id = (SELECT id FROM dock_jobs WHERE status = 'queued'
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
   RETURNING *;
   ```

4. Each job has a hard timeout of 180 seconds. On timeout or error, set `failed` with the last lines of stderr. The rest of the experiment stays saved.
5. Files go to `$RESULTS_DIR/{job_id}/` (`receptor.pdb`, `poses.sdf`, `scores.json`, `log.txt`) and are served from `/files/{job_id}/{name}`. Postgres stores metadata and scores, never file contents.

**C8. Viewer.** A starting point for React and 3Dmol.js. Check the import path against the installed `3dmol` version.

```tsx
import { useEffect, useRef } from "react";
import * as $3Dmol from "3dmol";

type Props = { receptorPdb: string; posesSdf: string; poseIndex: number; showSurface: boolean };

export function PoseViewer({ receptorPdb, posesSdf, poseIndex, showSurface }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const viewer = useRef<any>(null);

  useEffect(() => {
    viewer.current = $3Dmol.createViewer(el.current!, { backgroundColor: "white" });
    return () => viewer.current?.clear();
  }, []);

  useEffect(() => {
    const v = viewer.current;
    if (!v) return;
    v.clear();
    const receptor = v.addModel(receptorPdb, "pdb");
    receptor.setStyle({}, { cartoon: { color: "spectrum" } });
    const poses = posesSdf.split("$$$$").filter((s) => s.trim());
    const ligand = v.addModel(poses[poseIndex] + "$$$$\n", "sdf");
    ligand.setStyle({}, { stick: {} });
    if (showSurface) {
      v.addSurface($3Dmol.SurfaceType.VDW, { opacity: 0.6 },
        { model: receptor, within: { distance: 8, sel: { model: ligand } } });
    }
    v.zoomTo({ model: ligand });
    v.render();
  }, [receptorPdb, posesSdf, poseIndex, showSurface]);

  return <div ref={el} style={{ width: "100%", height: 480, position: "relative" }} />;
}
```

Keep the viewer instance in a ref, never in React state. Compute the surface only near the pocket and only when toggled on.

**C9. Pre-run the cache before judging.** Run and store every prepared structure's control, plus each demo pair (for example baricitinib → 6WTO and venetoclax → 6O0K), so nothing is computed for the first time during the demo.

**UI wording.** Use close to verbatim:
- **Next to the pose:** "This is a predicted binding pose: a geometric hypothesis for how this molecule could sit in this pocket of this particular crystal structure. It is not evidence that the drug binds this target, and it is not a prediction of clinical effect."
- **Next to the score:** "The docking score is a rough, unitless estimate of fit. It is not a measured binding affinity, it does not convert reliably to Kd or IC50, and scores are only loosely comparable between different ligands."
- **Next to the control:** "We validate the pipeline by re-docking a ligand whose true position is known from the crystal structure. A low RMSD means our setup reproduces a known answer; it says nothing about the novel pairs you explore."
