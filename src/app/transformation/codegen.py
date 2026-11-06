"""Stable facade for deterministic Dataflow code generation."""

from collections.abc import Callable

from app.transformation.codegen_common import UnsupportedOperator, missing_custom_functions
from app.transformation.codegen_python import (
    _py_expr,
    _python_custom_functions,
    python_source,
)
from app.transformation.codegen_r import _r_custom_functions, _r_expr, r_source
from app.transformation.codegen_sas import _sas_custom_functions, _sas_expr, sas_source
from app.transformation.contracts import DataflowIR

GENERATORS: dict[str, Callable[[DataflowIR, str], str]] = {
    "python": python_source,
    "r": r_source,
    "sas": sas_source,
}

__all__ = [
    "GENERATORS",
    "UnsupportedOperator",
    "_py_expr",
    "_python_custom_functions",
    "_r_custom_functions",
    "_r_expr",
    "_sas_custom_functions",
    "_sas_expr",
    "missing_custom_functions",
    "python_source",
    "r_source",
    "sas_source",
]
