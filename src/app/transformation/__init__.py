"""Internal transformation and compiler framework; no public universal plan."""

from app.transformation.contracts import AnalysisIR, DataflowIR
from app.transformation.evaluator import evaluate_dataflow
from app.transformation.service import compile_dataflow, ir_fingerprint, lineage

__all__ = [
    "AnalysisIR",
    "DataflowIR",
    "compile_dataflow",
    "evaluate_dataflow",
    "ir_fingerprint",
    "lineage",
]
