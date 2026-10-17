"""Fargate executor request and result-envelope invariants."""

from pathlib import Path
from uuid import uuid4

from app.execution.adapters import ExecutionLimits, ExecutionRequest
from app.execution.ecs import EcsExecutor


class _Waiter:
    def wait(self, **_arguments: object) -> None:
        return None


class _EcsClient:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.run_arguments: dict[str, object] | None = None
        self.stops: list[str] = []

    def list_tasks(self, **_arguments: object) -> dict[str, object]:
        return {"taskArns": []}

    def run_task(self, **arguments: object) -> dict[str, object]:
        self.run_arguments = arguments
        return {"tasks": [{"taskArn": "internal-task"}], "failures": []}

    def describe_tasks(self, **_arguments: object) -> dict[str, object]:
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {
            "tasks": [
                {
                    "lastStatus": status,
                    "containers": [{"name": "runner", "exitCode": 0}],
                }
            ]
        }

    def stop_task(self, **arguments: object) -> None:
        self.stops.append(str(arguments["reason"]))

    def get_waiter(self, _name: str) -> _Waiter:
        return _Waiter()


def _executor(root: Path, client: _EcsClient) -> EcsExecutor:
    return EcsExecutor(
        cluster="internal-cluster",
        task_definitions={"python": "python-task", "r": "r-task"},
        workspace_root=root,
        subnets=["subnet-a", "subnet-b"],
        security_groups=["sg-runner"],
        poll_interval_seconds=0,
        client=client,
    )


def _request(workspace: Path, *, output_bytes: int = 1024) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=uuid4(),
        language="python",
        workspace=workspace,
        image="ignored-by-digest-pinned-task-definition",
        limits=ExecutionLimits(
            cpu=2,
            memory_mb=4096,
            runtime_seconds=30,
            output_bytes=output_bytes,
        ),
    )


def test_executor_uses_private_awsvpc_task_and_reads_bounded_envelope(tmp_path: Path) -> None:
    workspace = tmp_path / "execution-1"
    result_directory = workspace / ".runner"
    result_directory.mkdir(parents=True)
    (result_directory / "stdout").write_bytes(b"ok")
    (result_directory / "stderr").write_bytes(b"")
    (result_directory / "exit-code").write_text("0", encoding="ascii")
    client = _EcsClient(["STOPPED"])

    result = _executor(tmp_path, client).execute(_request(workspace))

    assert result.status == "succeeded"
    assert result.stdout == b"ok"
    assert client.run_arguments is not None
    network = client.run_arguments["networkConfiguration"]
    assert network == {
        "awsvpcConfiguration": {
            "subnets": ["subnet-a", "subnet-b"],
            "securityGroups": ["sg-runner"],
            "assignPublicIp": "DISABLED",
        }
    }
    assert "internal-task" not in str(result)


def test_executor_stops_task_when_output_limit_is_exceeded(tmp_path: Path) -> None:
    workspace = tmp_path / "execution-2"
    (workspace / "outputs").mkdir(parents=True)
    (workspace / "outputs" / "large.csv").write_bytes(b"oversized")
    client = _EcsClient(["RUNNING"])

    result = _executor(tmp_path, client).execute(_request(workspace, output_bytes=2))

    assert result.status == "failed"
    assert result.failure == {"code": "execution_output_limit"}
    assert client.stops == ["execution output limit exceeded"]
