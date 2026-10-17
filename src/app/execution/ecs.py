"""AWS ECS Fargate implementation of the isolated executor boundary."""

import shutil
import time
from pathlib import Path
from typing import Any, cast

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings
from app.execution.adapters import ExecutionRequest, ExecutionResult


class EcsExecutor:
    """Run a staged program in a disposable, network-restricted Fargate task."""

    def __init__(
        self,
        *,
        cluster: str,
        task_definitions: dict[str, str],
        workspace_root: Path,
        subnets: list[str],
        security_groups: list[str],
        container_name: str = "runner",
        assign_public_ip: bool = False,
        poll_interval_seconds: float = 2.0,
        log_limit_bytes: int = 1_048_576,
        client: Any | None = None,
    ) -> None:
        self._cluster = cluster
        self._task_definitions = task_definitions
        self._workspace_root = workspace_root.resolve()
        self._subnets = subnets
        self._security_groups = security_groups
        self._container_name = container_name
        self._assign_public_ip = assign_public_ip
        self._poll_interval_seconds = poll_interval_seconds
        self._log_limit_bytes = log_limit_bytes
        self._client = client or boto3.client("ecs")

    @classmethod
    def from_settings(cls, settings: Settings) -> "EcsExecutor":
        """Construct the adapter from validated application settings."""

        if (
            settings.ecs_cluster_arn is None
            or settings.ecs_python_task_definition is None
            or settings.ecs_r_task_definition is None
            or settings.execution_workspace_root is None
        ):
            raise ValueError("ECS executor settings are incomplete")
        return cls(
            cluster=settings.ecs_cluster_arn,
            task_definitions={
                "python": settings.ecs_python_task_definition,
                "r": settings.ecs_r_task_definition,
            },
            workspace_root=Path(settings.execution_workspace_root),
            subnets=settings.ecs_subnets,
            security_groups=settings.ecs_security_groups,
            container_name=settings.ecs_runner_container_name,
            assign_public_ip=settings.ecs_assign_public_ip,
            poll_interval_seconds=settings.ecs_poll_interval_seconds,
            log_limit_bytes=settings.execution_log_limit_bytes,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if request.language not in self._task_definitions:
            raise ValueError("ECS execution supports only python and r")
        workspace = request.workspace.resolve(strict=True)
        try:
            relative_workspace = workspace.relative_to(self._workspace_root)
        except ValueError as error:
            raise ValueError("execution workspace is outside the configured EFS root") from error
        if not workspace.is_dir():
            raise ValueError("execution workspace must be a directory")

        program_name = "program.py" if request.language == "python" else "program.R"
        started_by = request.execution_id.hex
        try:
            self._stop_prior_tasks(started_by)
            self._remove_prior_workspaces(request.execution_id.hex, workspace)
            response = self._client.run_task(
                cluster=self._cluster,
                taskDefinition=self._task_definitions[request.language],
                launchType="FARGATE",
                platformVersion="LATEST",
                count=1,
                startedBy=started_by,
                enableExecuteCommand=False,
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": self._subnets,
                        "securityGroups": self._security_groups,
                        "assignPublicIp": "ENABLED" if self._assign_public_ip else "DISABLED",
                    }
                },
                overrides={
                    "cpu": str(max(256, int(request.limits.cpu * 1024))),
                    "memory": str(request.limits.memory_mb),
                    "containerOverrides": [
                        {
                            "name": self._container_name,
                            "command": [program_name],
                            "environment": [
                                {
                                    "name": "AURINARA_WORKSPACE",
                                    "value": f"/workspace/{relative_workspace.as_posix()}",
                                }
                            ],
                        }
                    ],
                },
                tags=[
                    {"key": "aurinara:execution-id", "value": str(request.execution_id)},
                    {"key": "aurinara:managed", "value": "true"},
                ],
            )
            failures = response.get("failures", [])
            tasks = response.get("tasks", [])
            if failures or len(tasks) != 1:
                return self._failed("executor_unavailable")
            task_arn = str(tasks[0]["taskArn"])
            deadline = time.monotonic() + request.limits.runtime_seconds
            task = self._wait(task_arn, request, deadline)
            if task is None:
                return self._read_result(
                    workspace,
                    status="cancelled",
                    failure="execution_cancelled",
                )
            if task.get("aurinaraOutputLimitExceeded"):
                return self._read_result(
                    workspace,
                    status="failed",
                    failure="execution_output_limit",
                )
            if time.monotonic() >= deadline and task.get("lastStatus") != "STOPPED":
                self._stop(task_arn, "execution timeout")
                self._wait_stopped(task_arn)
                return self._read_result(workspace, status="failed", failure="execution_timeout")
            container = self._container(task)
            exit_code = cast(int | None, container.get("exitCode"))
            if exit_code not in {0, None}:
                return self._read_result(
                    workspace,
                    status="failed",
                    failure="program_failed",
                    fallback_exit_code=exit_code,
                )
            return self._read_result(workspace, status="succeeded", fallback_exit_code=exit_code)
        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError):
            return self._failed("executor_unavailable")

    def _wait(
        self, task_arn: str, request: ExecutionRequest, deadline: float
    ) -> dict[str, Any] | None:
        while time.monotonic() < deadline:
            if request.cancel_requested():
                self._stop(task_arn, "execution cancelled")
                self._wait_stopped(task_arn)
                return None
            if self._output_bytes(request.workspace) > request.limits.output_bytes:
                self._stop(task_arn, "execution output limit exceeded")
                self._wait_stopped(task_arn)
                return {"aurinaraOutputLimitExceeded": True}
            task = self._describe(task_arn)
            if task.get("lastStatus") == "STOPPED":
                return task
            time.sleep(self._poll_interval_seconds)
        return self._describe(task_arn)

    def _describe(self, task_arn: str) -> dict[str, Any]:
        response = self._client.describe_tasks(cluster=self._cluster, tasks=[task_arn])
        tasks = response.get("tasks", [])
        if len(tasks) != 1:
            raise ValueError("ECS task disappeared")
        return cast(dict[str, Any], tasks[0])

    def _wait_stopped(self, task_arn: str) -> None:
        waiter = self._client.get_waiter("tasks_stopped")
        waiter.wait(
            cluster=self._cluster,
            tasks=[task_arn],
            WaiterConfig={"Delay": 2, "MaxAttempts": 60},
        )

    def _stop(self, task_arn: str, reason: str) -> None:
        self._client.stop_task(cluster=self._cluster, task=task_arn, reason=reason)

    def _stop_prior_tasks(self, started_by: str) -> None:
        response = self._client.list_tasks(cluster=self._cluster, startedBy=started_by)
        for task_arn in response.get("taskArns", []):
            self._stop(str(task_arn), "superseded execution attempt")
            self._wait_stopped(str(task_arn))

    def _remove_prior_workspaces(self, execution_id: str, current: Path) -> None:
        """Remove retry leftovers only after prior tasks for this execution stopped."""

        for candidate in self._workspace_root.glob(f"{execution_id}-*"):
            resolved = candidate.resolve()
            if resolved == current or not resolved.is_relative_to(self._workspace_root):
                continue
            shutil.rmtree(resolved, ignore_errors=True)

    @staticmethod
    def _output_bytes(workspace: Path) -> int:
        output_directory = workspace / "outputs"
        if not output_directory.is_dir():
            return 0
        try:
            return sum(
                path.stat().st_size
                for path in output_directory.rglob("*")
                if path.is_file()
            )
        except OSError:
            return 0

    def _container(self, task: dict[str, Any]) -> dict[str, Any]:
        for container in task.get("containers", []):
            if container.get("name") == self._container_name:
                return cast(dict[str, Any], container)
        raise ValueError("runner container result missing")

    def _read_result(
        self,
        workspace: Path,
        *,
        status: str,
        failure: str | None = None,
        fallback_exit_code: int | None = None,
    ) -> ExecutionResult:
        result_directory = workspace / ".runner"
        exit_code = fallback_exit_code
        exit_path = result_directory / "exit-code"
        if exit_path.is_file():
            exit_code = int(exit_path.read_text(encoding="ascii").strip())
        stdout = self._bounded_read(result_directory / "stdout")
        stderr = self._bounded_read(result_directory / "stderr")
        if status == "succeeded" and exit_code not in {0, None}:
            status = "failed"
            failure = "program_failed"
        return ExecutionResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            failure={"code": failure} if failure else None,
        )

    def _bounded_read(self, path: Path) -> bytes:
        if not path.is_file():
            return b""
        with path.open("rb") as handle:
            return handle.read(self._log_limit_bytes)

    @staticmethod
    def _failed(code: str) -> ExecutionResult:
        return ExecutionResult(
            status="failed",
            exit_code=None,
            stdout=b"",
            stderr=b"",
            failure={"code": code},
        )
