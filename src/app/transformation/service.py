"""Canonicalization, lineage, and deterministic compilation for internal IR."""

from dataclasses import dataclass

from app.common.canonical import fingerprint
from app.transformation.codegen import GENERATORS, UnsupportedOperator, missing_custom_functions
from app.transformation.contracts import DataflowIR


class BackendCapabilityMissing(ValueError):
    def __init__(self, backend: str, operator: str) -> None:
        self.backend = backend
        self.operator = operator
        super().__init__(f"{backend} cannot implement {operator}")


def canonical_ir(value: DataflowIR) -> dict[str, object]:
    payload = value.model_dump(mode="json")
    payload["nodes"] = sorted(payload["nodes"], key=lambda item: item["id"])
    payload["edges"] = sorted(
        payload["edges"], key=lambda item: (item["source_node"], item["target_node"])
    )
    return payload


def ir_fingerprint(value: DataflowIR) -> str:
    return fingerprint(canonical_ir(value))


def lineage(value: DataflowIR) -> dict[str, tuple[str, ...]]:
    incoming: dict[str, set[str]] = {node.id: set() for node in value.nodes}
    for edge in value.edges:
        incoming[edge.target_node].add(edge.source_node)

    def visit(identifier: str) -> set[str]:
        return incoming[identifier] | {
            ancestor for parent in incoming[identifier] for ancestor in visit(parent)
        }

    return {
        node.dataset: tuple(sorted(visit(node.id)))
        for node in value.nodes
        if node.node_type == "write"
    }


@dataclass(frozen=True, slots=True)
class CompiledProgram:
    backend: str
    compiler_version: str
    source: str
    ir_fingerprint: str
    executable: bool
    todo_functions: tuple[str, ...]


def compile_dataflow(value: DataflowIR, backend: str) -> CompiledProgram:
    if backend not in {"python", "r", "sas"}:
        raise ValueError("backend must be python, r, or sas")
    digest = ir_fingerprint(value)
    try:
        source = GENERATORS[backend](value, digest)
    except UnsupportedOperator as error:
        raise BackendCapabilityMissing(backend, str(error)) from error
    todo_functions = missing_custom_functions(value.custom_functions, backend)  # type: ignore[arg-type]
    return CompiledProgram(
        backend,
        "1.8.0",
        source,
        digest,
        executable=not todo_functions,
        todo_functions=todo_functions,
    )
