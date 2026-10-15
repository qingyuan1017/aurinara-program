"""Canonical Analysis IR handling and deterministic statistical code generation."""

import json
from dataclasses import dataclass

from app.common.canonical import fingerprint
from app.transformation.codegen import (
    _python_custom_functions,
    _r_custom_functions,
    _sas_custom_functions,
    missing_custom_functions,
)
from app.transformation.contracts import AnalysisIR


def canonical_analysis_ir(value: AnalysisIR) -> dict[str, object]:
    payload = value.model_dump(mode="json")
    payload["procedures"] = sorted(payload["procedures"], key=lambda item: item["id"])
    return payload


def analysis_ir_fingerprint(value: AnalysisIR) -> str:
    return fingerprint(canonical_analysis_ir(value))


@dataclass(frozen=True, slots=True)
class CompiledAnalysisProgram:
    backend: str
    compiler_version: str
    source: str
    ir_fingerprint: str
    executable: bool
    todo_functions: tuple[str, ...]


def compile_analysis(
    value: AnalysisIR, backend: str, output_filename: str
) -> CompiledAnalysisProgram:
    """Compile the supported Analysis IR subset without presentation semantics."""

    if backend not in {"python", "r", "sas"}:
        raise ValueError("backend must be python, r, or sas")
    digest = analysis_ir_fingerprint(value)
    payload = json.dumps(canonical_analysis_ir(value), sort_keys=True, separators=(",", ":"))
    if backend == "python":
        source = _python_source(value, payload, output_filename, digest)
    elif backend == "r":
        source = _r_source(value, payload, output_filename, digest)
    else:
        source = _sas_source(value, output_filename, digest)
    todo_functions = missing_custom_functions(value.custom_functions, backend)  # type: ignore[arg-type]
    return CompiledAnalysisProgram(
        backend,
        "1.1.0",
        source,
        digest,
        executable=not todo_functions,
        todo_functions=todo_functions,
    )


def _python_source(value: AnalysisIR, payload: str, output_filename: str, digest: str) -> str:
    custom_functions = _python_custom_functions(value.custom_functions)
    return f"""# Generated deterministically by Aurinara Analysis IR compiler 1.1.0
# IR fingerprint: {digest}
import csv, json, os, statistics
from pathlib import Path
{custom_functions}
IR = json.loads({payload!r})
root = Path(os.environ.get("AURINARA_WORKSPACE", "."))
rows_out = []
for procedure in IR["procedures"]:
    path = root / "inputs" / (procedure["input_dataset"] + ".csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    parameters = procedure["parameters"]
    for prefix in ("population", "parameter"):
        variable = parameters.get(prefix + "_variable")
        value = parameters.get(prefix + "_value")
        if variable:
            rows = [row for row in rows if row.get(variable) == str(value)]
    variable = str(parameters["variable"])
    base = {{"analysis_id": str(parameters["analysis_id"]), "row_id": str(parameters["row_id"])}}
    grouping = procedure.get("grouping", [])
    grouped = {{}}
    for row in rows:
        group_key = tuple(row.get(column, "") for column in grouping)
        grouped.setdefault(group_key, []).append(row)
    for group_key in sorted(grouped):
        group_rows = grouped[group_key]
        group_label = ";".join(
            f"{{column}}={{value}}" for column, value in zip(grouping, group_key)
        )
        if procedure["method"] == "custom":
            function_name = "aur_user_" + str(procedure["custom_function_id"])
            custom_rows = globals()[function_name](group_rows, parameters)
            if not isinstance(custom_rows, list) or not all(
                isinstance(item, dict) for item in custom_rows
            ):
                raise TypeError("custom TLF function must return a list of result dictionaries")
            for item in custom_rows:
                rows_out.append({{
                    **base,
                    "group": str(item.get("group", group_label)),
                    "statistic": str(item["statistic"]),
                    "value": str(item.get("value", "")),
                    "text": str(item.get("text", item.get("value", ""))),
                }})
        elif procedure["method"] == "frequency":
            counts = {{}}
            for row in group_rows:
                key = row.get(variable, "")
                counts[key] = counts.get(key, 0) + 1
            total = len(group_rows)
            for key in sorted(counts):
                count = counts[key]
                percent = 100 * count / total if total else 0
                category = f"{{variable}}={{key}}"
                rows_out.append({{
                    **base,
                    "group": ";".join(filter(None, (group_label, category))),
                    "statistic": "COUNT",
                    "value": str(count),
                    "text": f"{{count}} ({{percent:.1f}}%)",
                }})
        else:
            values = [
                float(row[variable])
                for row in group_rows
                if row.get(variable) not in (None, "")
            ]
            stats = [
                ("N", len(values)),
                ("MEAN", statistics.fmean(values) if values else None),
                ("MIN", min(values) if values else None),
                ("MAX", max(values) if values else None),
            ]
            for name, result in stats:
                text = (
                    "" if result is None
                    else str(result) if name == "N"
                    else f"{{result:.6g}}"
                )
                rows_out.append({{
                    **base, "group": group_label, "statistic": name,
                    "value": text, "text": text,
                }})
headers = ["analysis_id", "row_id", "group", "statistic", "value", "text"]
target = root / "outputs" / {output_filename!r}
with target.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\\n")
    writer.writeheader(); writer.writerows(rows_out)
"""


def _r_source(value: AnalysisIR, payload: str, output_filename: str, digest: str) -> str:
    escaped = payload.replace("\\", "\\\\").replace("'", "\\'")
    custom_functions = _r_custom_functions(value.custom_functions)
    return f"""# Generated deterministically by Aurinara Analysis IR compiler 1.1.0
# IR fingerprint: {digest}
library(jsonlite)
{custom_functions}
ir <- fromJSON('{escaped}', simplifyVector=FALSE)
root <- Sys.getenv("AURINARA_WORKSPACE", unset=".")
result <- data.frame(
  analysis_id=character(), row_id=character(), group=character(),
  statistic=character(), value=character(), text=character(),
  stringsAsFactors=FALSE
)
for (procedure in ir$procedures) {{
  input_path <- file.path(
    root, "inputs", paste0(procedure$input_dataset, ".csv")
  )
  rows <- read.csv(input_path, check.names=FALSE, stringsAsFactors=FALSE)
  p <- procedure$parameters
  for (prefix in c("population", "parameter")) {{
    variable <- p[[paste0(prefix, "_variable")]]
    value <- p[[paste0(prefix, "_value")]]
    if (!is.null(variable)) {{
      keep <- as.character(rows[[variable]]) == as.character(value)
      rows <- rows[keep, , drop=FALSE]
    }}
  }}
  variable <- p$variable
  grouping <- unlist(procedure$grouping)
  group_keys <- if (length(grouping) == 0) rep("", nrow(rows)) else apply(
    rows[, grouping, drop=FALSE], 1,
    function(values) paste(paste0(grouping, "=", values), collapse=";")
  )
  for (group_label in sort(unique(group_keys))) {{
    group_rows <- rows[group_keys == group_label, , drop=FALSE]
    if (procedure$method == "custom") {{
      function_name <- paste0("aur_user_", procedure$custom_function_id)
      custom_rows <- get(function_name, mode="function")(group_rows, p)
      required <- c("statistic", "value", "text")
      if (!is.data.frame(custom_rows) || !all(required %in% names(custom_rows))) {{
        stop("custom TLF function must return a data.frame with statistic, value, and text")
      }}
      if (!("group" %in% names(custom_rows))) custom_rows$group <- group_label
      custom_rows$analysis_id <- p$analysis_id
      custom_rows$row_id <- p$row_id
      result <- rbind(result, custom_rows[, c(
        "analysis_id", "row_id", "group", "statistic", "value", "text"
      )])
    }} else if (procedure$method == "frequency") {{
      counts <- table(as.character(group_rows[[variable]]), useNA="no")
      total <- nrow(group_rows)
      for (key in sort(names(counts))) {{
        count <- as.integer(counts[[key]])
        text <- sprintf(
          "%d (%.1f%%)", count, if (total == 0) 0 else 100 * count / total
        )
        category <- paste0(variable, "=", key)
        label <- paste(c(group_label, category)[nzchar(c(group_label, category))], collapse=";")
        result <- rbind(result, data.frame(
          analysis_id=p$analysis_id, row_id=p$row_id, group=label,
          statistic="COUNT", value=as.character(count), text=text,
          stringsAsFactors=FALSE
        ))
      }}
    }} else {{
      values <- suppressWarnings(as.numeric(group_rows[[variable]]))
      values <- values[!is.na(values)]
      stats <- list(
        N=length(values),
        MEAN=if(length(values)) mean(values) else NA,
        MIN=if(length(values)) min(values) else NA,
        MAX=if(length(values)) max(values) else NA
      )
      for (name in names(stats)) {{
        value <- stats[[name]]
        text <- if(is.na(value)) "" else if(name == "N") {{
          as.character(value)
        }} else {{
          format(value, digits=6, trim=TRUE)
        }}
        result <- rbind(result, data.frame(
          analysis_id=p$analysis_id, row_id=p$row_id, group=group_label,
          statistic=name, value=text, text=text, stringsAsFactors=FALSE
        ))
      }}
    }}
  }}
}}
write.table(
  result, file.path(root, "outputs", {json.dumps(output_filename)}),
  sep=",", row.names=FALSE, col.names=TRUE, quote=TRUE, na="",
  fileEncoding="UTF-8", eol="\\n"
)
"""


def _sas_source(value: AnalysisIR, output_filename: str, digest: str) -> str:
    lines = [
        "/* Generated deterministically by Aurinara Analysis IR compiler 1.1.0 */",
        f"/* IR fingerprint: {digest} */",
        f"/* Declared normalized result: {output_filename} */",
        _sas_custom_functions(value.custom_functions),
    ]
    for procedure in value.procedures:
        lines.append(
            f"/* {procedure.id}: {procedure.method} over {procedure.input_dataset}; "
            f"parameters={json.dumps(procedure.parameters, sort_keys=True)} */"
        )
    return "\n".join(lines) + "\n"
