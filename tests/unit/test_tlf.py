"""TLF manual-authoring, lowering, and deterministic compiler tests."""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tlf.contracts import (
    ArsAnalysis,
    TlfAdamDatasetBinding,
    TlfAnalysisStep,
    TlfArs,
    TlfBindings,
    TlfColumn,
    TlfNamedBinding,
    TlfProgramPlan,
    TlfRow,
    TlfShell,
)
from app.tlf.service import _render_output, lower_analysis_ir
from app.transformation.analysis import canonical_analysis_ir, compile_analysis


def _contracts() -> tuple[TlfShell, TlfBindings, TlfArs, TlfProgramPlan]:
    dataset_id = "adsl"
    shell = TlfShell(
        output_code="T-14-1",
        output_type="table",
        title="Subject disposition",
        columns=(TlfColumn(id="value", label="Subjects", order=1),),
        rows=(TlfRow(id="completed", label="Completed", order=1, leaf=True),),
        footnotes=("Percentages use the safety population denominator.",),
    )
    bindings = TlfBindings(
        datasets=(
            TlfAdamDatasetBinding(
                id=dataset_id,
                adam_id=uuid4(),
                adam_revision=3,
                dataset_code="ADSL",
                artifact_id=uuid4(),
                checksum="a" * 64,
                validation_run_id=uuid4(),
                dependency_fingerprint="b" * 64,
            ),
        ),
        named=(
            TlfNamedBinding(
                id="safety",
                kind="population",
                dataset_binding_id=dataset_id,
                variable="SAFFL",
                value="Y",
            ),
            TlfNamedBinding(
                id="frequency",
                kind="statistic",
                dataset_binding_id=dataset_id,
                variable="STAT",
                value="frequency",
            ),
        ),
    )
    ars = TlfArs(
        analyses=(
            ArsAnalysis(
                id="completed_analysis",
                leaf_row_id="completed",
                dataset_binding_id=dataset_id,
                population_binding_id="safety",
                statistic_binding_id="frequency",
                order=1,
            ),
        )
    )
    plan = TlfProgramPlan(
        shell_revision=1,
        bindings_revision=1,
        assumptions_revision=1,
        ars_revision=1,
        output_filename="t_14_1.csv",
        steps=(
            TlfAnalysisStep(
                id="frequency_step",
                analysis_id="completed_analysis",
                method="frequency",
                variable="EOSSTT",
                order=1,
            ),
        ),
    )
    return shell, bindings, ars, plan


def test_lowering_excludes_presentation_and_compilers_are_deterministic() -> None:
    shell, bindings, ars, plan = _contracts()
    internal = lower_analysis_ir(shell, bindings, ars, plan)
    canonical = canonical_analysis_ir(internal)
    serialized = json.dumps(canonical)

    assert "Subject disposition" not in serialized
    assert "footnotes" not in serialized
    assert canonical["procedures"][0]["parameters"]["row_id"] == "completed"

    python_one = compile_analysis(internal, "python", plan.output_filename)
    python_two = compile_analysis(internal, "python", plan.output_filename)
    assert python_one == python_two
    compile(python_one.source, "<tlf-program>", "exec")
    assert compile_analysis(internal, "r", plan.output_filename).ir_fingerprint == (
        python_one.ir_fingerprint
    )
    assert compile_analysis(internal, "sas", plan.output_filename).ir_fingerprint == (
        python_one.ir_fingerprint
    )


def test_custom_tlf_function_uses_typed_signature_and_language_todos(tmp_path: Path) -> None:
    shell, bindings, ars, original = _contracts()
    payload = original.model_dump(mode="json")
    payload["custom_functions"] = [
        {
            "id": "custom_count",
            "parameters": ["rows", "parameters"],
            "return_type": "result_rows",
            "implementations": [
                {
                    "language": "python",
                    "source": (
                        "return [{'statistic': 'N', 'value': len(rows), 'text': str(len(rows))}]"
                    ),
                }
            ],
        }
    ]
    payload["steps"][0]["method"] = "custom"
    payload["steps"][0]["custom_function_id"] = "custom_count"
    plan = TlfProgramPlan.model_validate(payload)
    internal = lower_analysis_ir(shell, bindings, ars, plan)

    python = compile_analysis(internal, "python", plan.output_filename)
    r = compile_analysis(internal, "r", plan.output_filename)
    assert python.executable is True
    assert "def aur_user_custom_count(rows, parameters):" in python.source
    assert r.executable is False
    assert r.todo_functions == ("custom_count",)
    assert "TODO: provide R implementation" in r.source

    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    inputs.mkdir()
    outputs.mkdir()
    with (inputs / "ADSL.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["SAFFL", "EOSSTT"])
        writer.writeheader()
        writer.writerow({"SAFFL": "Y", "EOSSTT": "COMPLETED"})
    source = tmp_path / "tlf.py"
    source.write_text(python.source, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-I", str(source)],
        check=False,
        capture_output=True,
        env={**os.environ, "AURINARA_WORKSPACE": str(tmp_path)},
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    with (outputs / plan.output_filename).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["statistic"] == "N"
    assert rows[0]["value"] == "1"


def test_custom_tlf_function_requires_analysis_signature() -> None:
    _, _, _, original = _contracts()
    payload = original.model_dump(mode="json")
    payload["custom_functions"] = [
        {
            "id": "bad_signature",
            "parameters": ["value"],
            "return_type": "result_rows",
            "implementations": [{"language": "python", "source": "return value"}],
        }
    ]
    payload["steps"][0]["method"] = "custom"
    payload["steps"][0]["custom_function_id"] = "bad_signature"
    with pytest.raises(ValidationError, match="rows.*parameters"):
        TlfProgramPlan.model_validate(payload)


def test_shell_rejects_incorrect_leaf_declaration() -> None:
    with pytest.raises(ValidationError, match="leaf flags"):
        TlfShell(
            output_code="T-1",
            output_type="table",
            title="Invalid",
            columns=(TlfColumn(id="value", label="Value", order=1),),
            rows=(
                TlfRow(id="parent", label="Parent", order=1, leaf=True),
                TlfRow(id="child", parent_id="parent", label="Child", order=2, leaf=True),
            ),
        )


def test_program_plan_requires_exact_ars_analysis_coverage() -> None:
    shell, bindings, ars, plan = _contracts()
    invalid = plan.model_copy(
        update={
            "steps": (
                *plan.steps,
                plan.steps[0].model_copy(update={"id": "extra", "order": 2}),
            )
        }
    )
    with pytest.raises(ValidationError, match="every ARS analysis"):
        TlfProgramPlan.model_validate(invalid.model_dump())
    assert lower_analysis_ir(shell, bindings, ars, plan).procedures[0].method == "frequency"


@pytest.mark.parametrize(
    ("artifact_type", "output_type", "signature", "media_type"),
    (
        ("tlf_table_rtf", "table", b"{\\rtf1", "application/rtf"),
        ("tlf_listing_pdf", "listing", b"%PDF", "application/pdf"),
        ("tlf_figure_png", "figure", b"\x89PNG\r\n\x1a\n", "image/png"),
        ("tlf_figure_svg", "figure", b"<svg", "image/svg+xml"),
        ("tlf_figure_pdf", "figure", b"%PDF", "application/pdf"),
    ),
)
def test_rendered_output_formats_are_real_files(
    artifact_type: str, output_type: str, signature: bytes, media_type: str
) -> None:
    shell, _, _, _ = _contracts()
    shell = shell.model_copy(update={"output_type": output_type})
    rows = [
        {
            "analysis_id": "completed_analysis",
            "row_id": "completed",
            "group": "Placebo",
            "statistic": "frequency",
            "value": "12",
            "text": "12",
        }
    ]

    data, filename, observed_media_type = _render_output(artifact_type, shell, rows)

    assert data.startswith(signature)
    assert filename.endswith(artifact_type.rsplit("_", 1)[-1])
    assert observed_media_type == media_type
