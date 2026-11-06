"""Shared graph ordering and custom-function contracts for code generation."""

from app.transformation.contracts import (
    CustomFunctionDefinition,
    CustomFunctionLanguage,
    DataflowIR,
    DataflowNode,
)


class UnsupportedOperator(ValueError):
    """Raised when a backend cannot preserve one operator's semantics."""


def _custom_name(identifier: str) -> str:
    return f"aur_user_{identifier}"


def missing_custom_functions(
    functions: tuple[CustomFunctionDefinition, ...], language: CustomFunctionLanguage
) -> tuple[str, ...]:
    """List functions for which generated source contains a TODO placeholder."""

    return tuple(item.id for item in functions if item.implementation(language) is None)


def ordered_nodes(value: DataflowIR) -> tuple[DataflowNode, ...]:
    nodes = {node.id: node for node in value.nodes}
    degree = dict.fromkeys(nodes, 0)
    outgoing: dict[str, list[str]] = {name: [] for name in nodes}
    for edge in value.edges:
        degree[edge.target_node] += 1
        outgoing[edge.source_node].append(edge.target_node)
    queue = sorted(name for name, count in degree.items() if count == 0)
    result: list[DataflowNode] = []
    while queue:
        name = queue.pop(0)
        result.append(nodes[name])
        for target in sorted(outgoing[name]):
            degree[target] -= 1
            if degree[target] == 0:
                queue.append(target)
                queue.sort()
    return tuple(result)


def incoming_nodes(value: DataflowIR) -> dict[str, tuple[str, ...]]:
    inputs: dict[str, list[str]] = {node.id: [] for node in value.nodes}
    for edge in value.edges:
        inputs[edge.target_node].append(edge.source_node)
    return {name: tuple(sorted(items)) for name, items in inputs.items()}


def _single(node: DataflowNode, incoming: tuple[str, ...]) -> str:
    if len(incoming) != 1:
        raise UnsupportedOperator(f"{node.node_type}_input_arity")
    return incoming[0]
