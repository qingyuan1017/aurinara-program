"""Real isolated Python/R runner conformance for one canonical Dataflow IR."""

import csv
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.adam.contracts import AdamDerivationPlan, AdamSpecification
from app.adam.service import lower_plan
from app.execution.adapters import DockerExecutor, ExecutionLimits, ExecutionRequest
from app.transformation.contracts import DataflowIR
from app.transformation.service import compile_dataflow

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_RUNNER_INTEGRATION") != "1",
    reason="set AURINARA_RUNNER_INTEGRATION=1 after building both runner images",
)


def _flow() -> DataflowIR:
    return DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "read", "dataset": "DEMOG"},
                {
                    "node_type": "derive",
                    "id": "derive",
                    "assignments": {
                        "STUDYID": {"kind": "literal", "value": "SYN-001"},
                        "USUBJID": {
                            "kind": "column",
                            "dataset": "DEMOG",
                            "column": "SUBJID",
                        },
                    },
                },
                {
                    "node_type": "select",
                    "id": "select",
                    "columns": ["STUDYID", "USUBJID"],
                },
                {"node_type": "write", "id": "write", "dataset": "DM"},
            ],
            "edges": [
                {"source_node": "read", "target_node": "derive"},
                {"source_node": "derive", "target_node": "select"},
                {"source_node": "select", "target_node": "write"},
            ],
        }
    )


def _advanced_flow() -> DataflowIR:
    return DataflowIR.model_validate(
        {
            "nodes": [
                {"node_type": "read", "id": "subjects", "dataset": "SUBJECTS"},
                {"node_type": "read", "id": "sites", "dataset": "SITES"},
                {
                    "node_type": "join",
                    "id": "joined",
                    "join_type": "left",
                    "left_input": "subjects",
                    "right_input": "sites",
                    "keys": [["SITEID", "SITEID"]],
                },
                {
                    "node_type": "terminology_map",
                    "id": "mapped",
                    "source_column": "SEX",
                    "target_column": "SEXDEC",
                    "mappings": {"M": "Male", "F": "Female"},
                },
                {
                    "node_type": "cast",
                    "id": "cast_values",
                    "casts": {
                        "V1": {"source_column": "V1", "target_type": "float"},
                        "V2": {"source_column": "V2", "target_type": "float"},
                    },
                },
                {
                    "node_type": "pivot_longer",
                    "id": "long",
                    "id_columns": ["SEXDEC"],
                    "value_columns": ["V1", "V2"],
                    "name_column": "VISIT",
                    "value_column": "VALUE",
                },
                {
                    "node_type": "sequence",
                    "id": "sequenced",
                    "group_by": ["SEXDEC"],
                    "order_by": ["VISIT"],
                    "target_column": "SEQ",
                },
                {
                    "node_type": "window",
                    "id": "windowed",
                    "partition_by": ["SEXDEC"],
                    "order_by": ["VISIT"],
                    "operations": {
                        "ROW_NUMBER": {"operation": "row_number"},
                        "PREVIOUS": {
                            "operation": "lag",
                            "source_column": "VALUE",
                        },
                        "RUNNING": {
                            "operation": "cumulative_sum",
                            "source_column": "VALUE",
                        },
                    },
                },
                {
                    "node_type": "aggregate",
                    "id": "summary",
                    "group_by": ["SEXDEC"],
                    "aggregations": {
                        "N": {"operation": "count"},
                        "TOTAL": {"operation": "sum", "column": "VALUE"},
                    },
                },
                {"node_type": "sort", "id": "sorted", "keys": ["SEXDEC"]},
                {"node_type": "write", "id": "write", "dataset": "SUMMARY"},
            ],
            "edges": [
                {"source_node": "subjects", "target_node": "joined"},
                {"source_node": "sites", "target_node": "joined"},
                {"source_node": "joined", "target_node": "cast_values"},
                {"source_node": "cast_values", "target_node": "mapped"},
                {"source_node": "mapped", "target_node": "long"},
                {"source_node": "long", "target_node": "sequenced"},
                {"source_node": "sequenced", "target_node": "windowed"},
                {"source_node": "windowed", "target_node": "summary"},
                {"source_node": "summary", "target_node": "sorted"},
                {"source_node": "sorted", "target_node": "write"},
            ],
        }
    )


def _adam_flow() -> DataflowIR:
    specification = AdamSpecification.model_validate(
        {
            "datasets": [
                {
                    "id": "10000000-0000-0000-0000-000000000001",
                    "code": "ADSL",
                    "label": "Subject-Level Analysis Dataset",
                    "dataset_class": "SUBJECT LEVEL ANALYSIS DATASET",
                    "structure": "One record per subject",
                    "keys": ["USUBJID"],
                    "sort_order": ["USUBJID"],
                    "expected_output_name": "adsl.xpt",
                    "variables": [
                        {
                            "id": "20000000-0000-0000-0000-000000000001",
                            "name": "USUBJID",
                            "label": "Unique Subject Identifier",
                            "data_type": "character",
                            "length": 40,
                            "role": "Identifier",
                            "origin": {
                                "origin_type": "Predecessor",
                                "source_kind": "sdtm",
                                "source_dataset": "DM",
                                "source_variable": "USUBJID",
                            },
                            "output_node_id": "read_dm",
                        },
                        {
                            "id": "20000000-0000-0000-0000-000000000002",
                            "name": "TRT01P",
                            "label": "Planned Treatment Period 01",
                            "data_type": "character",
                            "length": 20,
                            "role": "Treatment",
                            "origin": {
                                "origin_type": "Derived",
                                "description": "Copy the planned SDTM arm.",
                            },
                            "method_id": "MT.TRT01P",
                            "output_node_id": "derive_trt",
                        },
                    ],
                }
            ],
            "methods": [
                {
                    "id": "MT.TRT01P",
                    "name": "Planned treatment",
                    "description": "Copy the planned SDTM arm.",
                    "plan_node_ids": ["derive_trt"],
                }
            ],
        }
    )
    plan = AdamDerivationPlan.model_validate(
        {
            "specification_revision": 1,
            "input_selection_revision": 1,
            "nodes": [
                {"node_type": "sdtm_read", "id": "read_dm", "dataset": "DM"},
                {
                    "node_type": "derive",
                    "id": "derive_trt",
                    "target_dataset": "ADSL",
                    "method_id": "MT.TRT01P",
                    "assignments": {"TRT01P": {"kind": "column", "dataset": "DM", "column": "ARM"}},
                },
                {
                    "node_type": "select",
                    "id": "select_adsl",
                    "columns": ["USUBJID", "TRT01P"],
                },
                {"node_type": "dataset_write", "id": "write_adsl", "dataset": "ADSL"},
            ],
            "edges": [
                {"source_node": "read_dm", "target_node": "derive_trt"},
                {"source_node": "derive_trt", "target_node": "select_adsl"},
                {"source_node": "select_adsl", "target_node": "write_adsl"},
            ],
        }
    )
    return lower_plan(specification, plan)


def _run(tmp_path: Path, language: str, image: str) -> list[dict[str, str]]:
    workspace = tmp_path / language
    inputs = workspace / "inputs"
    outputs = workspace / "outputs"
    inputs.mkdir(parents=True)
    outputs.mkdir()
    workspace.chmod(0o755)
    inputs.chmod(0o755)
    outputs.chmod(0o777)
    with (inputs / "DEMOG.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["SUBJID", "AGE"])
        writer.writeheader()
        writer.writerows([{"SUBJID": "01", "AGE": "42"}, {"SUBJID": "02", "AGE": "38"}])
    program = workspace / ("program.py" if language == "python" else "program.R")
    program.write_text(compile_dataflow(_flow(), language).source, encoding="utf-8")
    result = DockerExecutor().execute(
        ExecutionRequest(
            execution_id=uuid4(),
            language=language,
            workspace=workspace,
            image=image,
            limits=ExecutionLimits(
                cpu=1,
                memory_mb=512,
                runtime_seconds=30,
                output_bytes=1_048_576,
            ),
        )
    )
    assert result.status == "succeeded", result.stderr.decode(errors="replace")
    with (outputs / "DM.csv").open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_python_and_r_produce_equivalent_discrete_results(tmp_path: Path) -> None:
    python_rows = _run(tmp_path, "python", "aurinara-python-runner:local")
    r_rows = _run(tmp_path, "r", "aurinara-r-runner:local")

    assert (
        python_rows
        == r_rows
        == [
            {"STUDYID": "SYN-001", "USUBJID": "01"},
            {"STUDYID": "SYN-001", "USUBJID": "02"},
        ]
    )


def test_python_and_r_execute_advanced_operators(tmp_path: Path) -> None:
    datasets = {
        "SUBJECTS": [
            {"SITEID": "A", "SEX": "M", "V1": "10", "V2": "20"},
            {"SITEID": "B", "SEX": "F", "V1": "4", "V2": "8"},
        ],
        "SITES": [{"SITEID": "A", "COUNTRY": "US"}],
    }
    results: dict[str, list[dict[str, str]]] = {}
    for language, image in (
        ("python", "aurinara-python-runner:local"),
        ("r", "aurinara-r-runner:local"),
    ):
        workspace = tmp_path / f"advanced-{language}"
        inputs = workspace / "inputs"
        outputs = workspace / "outputs"
        inputs.mkdir(parents=True)
        outputs.mkdir()
        workspace.chmod(0o755)
        inputs.chmod(0o755)
        outputs.chmod(0o777)
        for name, rows in datasets.items():
            with (inputs / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        extension = "py" if language == "python" else "R"
        (workspace / f"program.{extension}").write_text(
            compile_dataflow(_advanced_flow(), language).source,
            encoding="utf-8",
        )
        result = DockerExecutor().execute(
            ExecutionRequest(
                execution_id=uuid4(),
                language=language,
                workspace=workspace,
                image=image,
                limits=ExecutionLimits(
                    cpu=1,
                    memory_mb=512,
                    runtime_seconds=30,
                    output_bytes=1_048_576,
                ),
            )
        )
        assert result.status == "succeeded", result.stderr.decode(errors="replace")
        with (outputs / "SUMMARY.csv").open(encoding="utf-8-sig", newline="") as stream:
            results[language] = list(csv.DictReader(stream))

    for language_rows in results.values():
        assert [(row["SEXDEC"], row["N"]) for row in language_rows] == [
            ("Female", "2"),
            ("Male", "2"),
        ]
        assert [float(row["TOTAL"]) for row in language_rows] == [12.0, 30.0]


def test_adam_specification_and_plan_match_in_python_and_r(tmp_path: Path) -> None:
    internal = _adam_flow()
    expected = [
        {"USUBJID": "01", "TRT01P": "Placebo"},
        {"USUBJID": "02", "TRT01P": "Active"},
    ]
    results: dict[str, list[dict[str, str]]] = {}
    compiler_fingerprints: set[str] = set()
    for language, image in (
        ("python", "aurinara-python-runner:local"),
        ("r", "aurinara-r-runner:local"),
    ):
        workspace = tmp_path / f"adam-{language}"
        inputs = workspace / "inputs"
        outputs = workspace / "outputs"
        inputs.mkdir(parents=True)
        outputs.mkdir()
        workspace.chmod(0o755)
        inputs.chmod(0o755)
        outputs.chmod(0o777)
        with (inputs / "DM.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["USUBJID", "ARM"])
            writer.writeheader()
            writer.writerows(
                [
                    {"USUBJID": "01", "ARM": "Placebo"},
                    {"USUBJID": "02", "ARM": "Active"},
                ]
            )
        compiled = compile_dataflow(internal, language)
        compiler_fingerprints.add(compiled.ir_fingerprint)
        extension = "py" if language == "python" else "R"
        (workspace / f"program.{extension}").write_text(compiled.source, encoding="utf-8")
        result = DockerExecutor().execute(
            ExecutionRequest(
                execution_id=uuid4(),
                language=language,
                workspace=workspace,
                image=image,
                limits=ExecutionLimits(
                    cpu=1,
                    memory_mb=512,
                    runtime_seconds=30,
                    output_bytes=1_048_576,
                ),
            )
        )
        assert result.status == "succeeded", result.stderr.decode(errors="replace")
        with (outputs / "ADSL.csv").open(encoding="utf-8-sig", newline="") as stream:
            results[language] = list(csv.DictReader(stream))

    assert len(compiler_fingerprints) == 1
    assert results == {"python": expected, "r": expected}


def test_python_runner_denies_network_root_and_root_filesystem_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "isolation"
    (workspace / "inputs").mkdir(parents=True)
    (workspace / "outputs").mkdir()
    workspace.chmod(0o755)
    (workspace / "outputs").chmod(0o777)
    (workspace / "program.py").write_text(
        """import os
import socket
from pathlib import Path
if os.getuid() == 0:
    raise RuntimeError("runner is root")
try:
    socket.create_connection(("1.1.1.1", 80), timeout=1)
except OSError:
    pass
else:
    raise RuntimeError("network is available")
try:
    Path("/forbidden").write_text("unsafe")
except OSError:
    pass
else:
    raise RuntimeError("root filesystem is writable")
Path("/workspace/outputs/EVIDENCE.csv").write_text("control,status\\nisolation,passed\\n")
""",
        encoding="utf-8",
    )
    result = DockerExecutor().execute(
        ExecutionRequest(
            execution_id=uuid4(),
            language="python",
            workspace=workspace,
            image="aurinara-python-runner:local",
            limits=ExecutionLimits(cpu=1, memory_mb=256, runtime_seconds=10, output_bytes=1024),
        )
    )

    assert result.status == "succeeded", result.stderr.decode(errors="replace")


def test_cancel_stops_and_removes_python_container(tmp_path: Path) -> None:
    workspace = tmp_path / "cancel"
    (workspace / "inputs").mkdir(parents=True)
    (workspace / "outputs").mkdir()
    workspace.chmod(0o755)
    (workspace / "outputs").chmod(0o777)
    (workspace / "program.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    execution_id = uuid4()
    result = DockerExecutor().execute(
        ExecutionRequest(
            execution_id=execution_id,
            language="python",
            workspace=workspace,
            image="aurinara-python-runner:local",
            limits=ExecutionLimits(cpu=1, memory_mb=256, runtime_seconds=10, output_bytes=1024),
            cancel_requested=lambda: True,
        )
    )

    containers = subprocess.run(
        ["docker", "ps", "--quiet", "--filter", f"name=aurinara-{execution_id.hex}"],
        check=False,
        capture_output=True,
        timeout=10,
    )
    assert result.status == "cancelled"
    assert not containers.stdout.strip()
