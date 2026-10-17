"""Isolated executor interface and local Docker implementation."""

import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    cpu: float
    memory_mb: int
    runtime_seconds: int
    output_bytes: int


def _never_cancel() -> bool:
    return False


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    execution_id: UUID
    language: str
    workspace: Path
    image: str
    limits: ExecutionLimits
    cancel_requested: Callable[[], bool] = _never_cancel


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    failure: dict[str, object] | None = None


class Executor(Protocol):
    """Boundary implemented by local containers and production task dispatchers."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute a staged immutable program and return bounded process evidence."""


class DockerExecutor:
    """Run a staged Python or R program in a locked-down disposable container."""

    def __init__(
        self,
        *,
        executable: str = "docker",
        network_disabled: bool = True,
        log_limit_bytes: int = 1_048_576,
    ) -> None:
        self.executable = executable
        self.network_disabled = network_disabled
        self.log_limit_bytes = log_limit_bytes

    def command(self, request: ExecutionRequest) -> list[str]:
        """Build a fixed-argument command without invoking a shell."""

        workspace = request.workspace.resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("execution workspace must be a directory")
        programs = {"python": "/workspace/program.py", "r": "/workspace/program.R"}
        if request.language not in programs:
            raise ValueError("Docker execution supports only python and r")
        command = [
            self.executable,
            "run",
            "--rm",
            "--name",
            f"aurinara-{request.execution_id.hex}",
            "--read-only",
            "--user",
            "10001:10001",
            "--pids-limit",
            "128",
            "--cpus",
            str(request.limits.cpu),
            "--memory",
            f"{request.limits.memory_mb}m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
        ]
        if self.network_disabled:
            command.extend(["--network", "none"])
        command.extend(
            [
                "--mount",
                f"type=bind,source={workspace},target=/workspace",
                request.image,
                programs[request.language],
            ]
        )
        return command

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        command = self.command(request)
        try:
            process = subprocess.Popen(
                command,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            return ExecutionResult(
                status="failed",
                exit_code=None,
                stdout=b"",
                stderr=b"",
                failure={"code": "executor_unavailable", "detail": type(error).__name__},
            )
        deadline = time.monotonic() + request.limits.runtime_seconds
        while True:
            try:
                stdout_value, stderr_value = process.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired as error:
                if request.cancel_requested():
                    self._remove_container(request.execution_id)
                    process.kill()
                    stdout_value, stderr_value = process.communicate()
                    return ExecutionResult(
                        status="cancelled",
                        exit_code=None,
                        stdout=self._bounded(stdout_value or error.stdout or b""),
                        stderr=self._bounded(stderr_value or error.stderr or b""),
                        failure={"code": "execution_cancelled"},
                    )
                if time.monotonic() >= deadline:
                    self._remove_container(request.execution_id)
                    process.kill()
                    stdout_value, stderr_value = process.communicate()
                    return ExecutionResult(
                        status="failed",
                        exit_code=None,
                        stdout=self._bounded(stdout_value or error.stdout or b""),
                        stderr=self._bounded(stderr_value or error.stderr or b""),
                        failure={"code": "execution_timeout"},
                    )
        stdout = self._bounded(stdout_value)
        stderr = self._bounded(stderr_value)
        result_directory = request.workspace / ".runner"
        if result_directory.is_dir():
            stdout = self._read_result(result_directory / "stdout")
            stderr = self._read_result(result_directory / "stderr")
        if process.returncode != 0:
            return ExecutionResult(
                status="failed",
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                failure={"code": "program_failed"},
            )
        return ExecutionResult(
            status="succeeded",
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def _bounded(self, value: bytes) -> bytes:
        return value[: self.log_limit_bytes]

    def _read_result(self, path: Path) -> bytes:
        if not path.is_file():
            return b""
        with path.open("rb") as handle:
            return handle.read(self.log_limit_bytes)

    def _remove_container(self, execution_id: UUID) -> None:
        with suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                [self.executable, "rm", "--force", f"aurinara-{execution_id.hex}"],
                shell=False,
                capture_output=True,
                check=False,
                timeout=10,
            )
