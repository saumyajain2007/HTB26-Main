"""Boltz publication preserves joint coordinates and rejects incomplete outputs."""

import json
from uuid import UUID

import pytest
from htb_api.services.boltz import load_prediction

from htb_worker.boltz import protein_sequence, publish

PROFILE = UUID("00000000-0000-4000-8000-000000000001")


def test_publish_complex_and_detect_corruption(tmp_path):
    model = tmp_path / "complex.pdb"
    protein = "ATOM      1  CA  ALA A   1      11.000  12.000  13.000  1.00 80.00           C"
    ligand = "HETATM    2  C1  LIG B   1      14.000  15.000  16.000  1.00 80.00           C"
    model.write_text(protein + "\n" + ligand + "\nEND\n")
    confidence = tmp_path / "confidence.json"
    confidence.write_text(json.dumps({"confidence_score": 0.85}))
    root = tmp_path / "results"
    directory = publish(
        model=model,
        confidence=confidence,
        root=root,
        profile_id=PROFILE,
        candidate_id="CHEMBL1",
        smiles="C",
        target_name="Test target",
        sequence="ACDE",
        version="test",
    )
    prediction = load_prediction(root, PROFILE, "CHEMBL1")
    assert prediction is not None
    assert prediction.confidence_score == 0.85
    assert (directory / "receptor.pdb").read_text() == protein + "\nEND\n"
    assert (directory / "ligand.pdb").read_text() == ligand + "\nEND\n"
    assert prediction.ligand.url.endswith("/boltz/ligand.pdb")
    assert load_prediction(root, PROFILE, "another") is None
    (directory / "ligand.pdb").write_text("corrupt")
    with pytest.raises(ValueError, match="checksum"):
        load_prediction(root, PROFILE, "CHEMBL1")


def test_reject_missing_ligand(tmp_path):
    model = tmp_path / "complex.pdb"
    model.write_text("ATOM      1  CA  ALA A   1      11.000  12.000  13.000\n")
    with pytest.raises(ValueError, match="chain B"):
        publish(
            model=model,
            confidence=tmp_path / "missing",
            root=tmp_path,
            profile_id=PROFILE,
            candidate_id="x",
            smiles="C",
            target_name="x",
            sequence="ACDE",
            version="test",
        )


def test_sequence_requires_one_protein(tmp_path):
    fasta = tmp_path / "protein.fa"
    fasta.write_text(">target\nACDE\nFGHI\n")
    assert protein_sequence(fasta) == "ACDEFGHI"
    fasta.write_text(">one\nACDE\n>two\nFGHI\n")
    with pytest.raises(ValueError, match="multiple"):
        protein_sequence(fasta)


def test_cli_runs_boltz_and_publishes_completed_output(tmp_path, monkeypatch):
    import htb_worker.boltz as module

    fasta = tmp_path / "protein.fa"
    fasta.write_text(">test\nACDE\n")
    monkeypatch.setattr(module.importlib.metadata, "version", lambda _: "2.2.1")
    commands = []

    def predict(command, *, check):
        assert check
        commands.append(command)
        source = module.Path(command[2])
        specification = json.loads(source.read_text())
        assert specification["sequences"][0]["protein"]["sequence"] == "ACDE"
        assert specification["sequences"][1]["ligand"]["smiles"] == "C"
        output = module.Path(command[command.index("--out_dir") + 1]) / "predictions" / "complex"
        output.mkdir(parents=True)
        (output / "complex_model_0.pdb").write_text(
            "ATOM      1  CA  ALA A   1      11.000  12.000  13.000\n"
            "HETATM    2  C1  LIG B   1      14.000  15.000  16.000\nEND\n"
        )
        (output / "confidence_complex_model_0.json").write_text('{"confidence_score": 0.9}')

    monkeypatch.setattr(module.subprocess, "run", predict)
    monkeypatch.setattr(
        "sys.argv",
        [
            "boltz",
            "--profile-id",
            str(PROFILE),
            "--candidate-id",
            "CHEMBL1",
            "--smiles",
            "C",
            "--target-name",
            "test target",
            "--sequence",
            str(fasta),
            "--out",
            str(tmp_path / "results"),
        ],
    )
    module.main()
    assert "--use_msa_server" in commands[0]
    assert commands[0][commands[0].index("--model") + 1] == "boltz2"
    assert commands[0][commands[0].index("--output_format") + 1] == "pdb"
    assert load_prediction(tmp_path / "results", PROFILE, "CHEMBL1") is not None


def test_exploratory_publication_requires_and_preserves_limitations(tmp_path):
    model = tmp_path / "complex.pdb"
    model.write_text(
        "ATOM      1  CA  ALA A   1      11.000  12.000  13.000\n"
        "HETATM    2  C1  LIG B   1      14.000  15.000  16.000\nEND\n"
    )
    confidence = tmp_path / "confidence.json"
    confidence.write_text('{"confidence_score": 0.7}')

    def attempt(notes=None):
        return publish(
            model=model,
            confidence=confidence,
            root=tmp_path / "results",
            profile_id=PROFILE,
            candidate_id="test",
            smiles="C",
            target_name="PBP construct",
            sequence="ACDE",
            version="test",
            prediction_scope="exploratory",
            limitations=notes,
        )

    with pytest.raises(ValueError, match="input assumptions"):
        attempt()
    attempt(["Truncated receptor; isoform assumed."])
    result = load_prediction(tmp_path / "results", PROFILE, "test")
    assert result is not None
    assert result.prediction_scope == "exploratory"
    assert result.limitations == ["Truncated receptor; isoform assumed."]
