"""Execution isolation command policy tests."""

from pathlib import Path
from uuid import UUID

from app.execution.adapters import DockerExecutor, ExecutionLimits, ExecutionRequest


def test_docker_command_enforces_isolation_and_limits(tmp_path: Path) -> None:
    command = DockerExecutor().command(
        ExecutionRequest(
            execution_id=UUID("00000000-0000-0000-0000-000000000123"),
            language="python",
            workspace=tmp_path,
            image="runner@sha256:example",
            limits=ExecutionLimits(cpu=1.5, memory_mb=512, runtime_seconds=60, output_bytes=10),
        )
    )

    assert command[0:2] == ["docker", "run"]
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--cap-drop" in command and command[command.index("--cap-drop") + 1] == "ALL"
    assert "--pids-limit" in command
    assert command[-2:] == ["runner@sha256:example", "/workspace/program.py"]
