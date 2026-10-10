"""TLF manual-authoring, lowering, and deterministic compiler tests."""

import json
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
