"""Deterministic R emission from Dataflow IR."""

from app.transformation.codegen_common import (
    UnsupportedOperator,
    _custom_name,
    _single,
    incoming_nodes,
    ordered_nodes,
)
from app.transformation.contracts import (
    CustomFunctionDefinition,
    DataflowIR,
    DerivationExpression,
)


def _r_custom_functions(functions: tuple[CustomFunctionDefinition, ...]) -> str:
    blocks: list[str] = []
    for definition in functions:
        source = definition.implementation("r")
        parameters = ", ".join(definition.parameters)
        if source is None:
            source = (
                f"# TODO: provide R implementation for custom function {definition.id}\n"
                f"stop('custom_function_todo:{definition.id}:r')"
            )
        blocks.append(f"{_custom_name(definition.id)} <- function({parameters}) {{\n{source}\n}}")
    return "\n\n".join(blocks)


def _rq(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _r_mapping(value: dict[str, str]) -> str:
    return "c(" + ", ".join(f"{_rq(key)}={_rq(mapped)}" for key, mapped in value.items()) + ")"


def _r_literal_scalar(value: str | int | float | bool | None) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return _rq(value)
    return repr(value)


def _r_expr(expression: DerivationExpression, frame: str = "frame") -> str:
    if expression.kind == "literal":
        if expression.value is None:
            return "NA"
        if isinstance(expression.value, bool):
            return "TRUE" if expression.value else "FALSE"
        return (
            _rq(expression.value) if isinstance(expression.value, str) else repr(expression.value)
        )
    if expression.kind == "column":
        return f"{frame}[[{_rq(expression.column)}]]"
    if expression.kind == "conditional":
        result = f"aur_norm({_r_expr(expression.otherwise, frame)})"
        for branch in reversed(expression.branches):
            when = _r_expr(branch.when, frame)
            then = f"aur_norm({_r_expr(branch.then, frame)})"
            result = f"ifelse(({when}) & !is.na({when}), {then}, {result})"
        return result
    if expression.kind == "list_literal":
        items = ", ".join(_r_literal_scalar(value) for value in expression.values)
        return f"list({items})"
    if expression.kind == "function":
        if expression.function == "is_in":
            value = _r_expr(expression.arguments[0], frame)
            candidates = _r_expr(expression.arguments[1], frame)
            return f"aur_is_in({value}, {candidates})"
        arguments = ", ".join(_r_expr(argument, frame) for argument in expression.arguments)
        return f"aur_{expression.function}({arguments})"
    if expression.kind == "custom_function":
        arguments = ", ".join(_r_expr(argument, frame) for argument in expression.arguments)
        return f"{_custom_name(expression.function_id)}({arguments})"
    if expression.kind == "cast":
        return (
            f"aur_cast({_r_expr(expression.value, frame)}, "
            f"{_rq(expression.target_type)}, {_rq(expression.invalid)})"
        )
    if expression.kind == "terminology_map":
        return (
            f"aur_terminology_map({_r_expr(expression.value, frame)}, "
            f"{_r_mapping(expression.mappings)}, {_rq(expression.unmapped)})"
        )
    if expression.kind == "unary":
        operand = _r_expr(expression.operand, frame)
        return {
            "not": f"!({operand})",
            "is_null": f"is.na({operand})",
            "is_not_null": f"!is.na({operand})",
            "negate": f"-as.numeric({operand})",
        }[expression.operator]
    left, right = _r_expr(expression.left, frame), _r_expr(expression.right, frame)
    symbols = {
        "eq": "==",
        "ne": "!=",
        "lt": "<",
        "le": "<=",
        "gt": ">",
        "ge": ">=",
        "and": "&",
        "or": "|",
        "add": "+",
        "sub": "-",
        "mul": "*",
        "div": "/",
    }
    if expression.operator in {"add", "sub", "mul", "div"}:
        left, right = f"as.numeric({left})", f"as.numeric({right})"
    return f"({left} {symbols[expression.operator]} {right})"


_R_FUNCTION_PREAMBLE = r"""
aur_norm <- function(x) { if (is.numeric(x)) x[!is.finite(x)] <- NA; x }
.aur_na <- function(x) is.na(x) | (is.character(x) & is.na(suppressWarnings(x)))
.aur_txt <- function(x) {
  if (is.logical(x)) ifelse(is.na(x), NA_character_, ifelse(x, "1", "0")) else as.character(x)
}
.aur_num <- function(x) suppressWarnings(as.numeric(x))
.aur_int <- function(x) suppressWarnings(as.integer(round(as.numeric(x))))
aur_cast <- function(x, target, invalid) {
  missing <- is.na(x) | x == ""
  if (target == "text") converted <- as.character(x)
  else if (target == "float") converted <- suppressWarnings(as.numeric(x))
  else if (target == "integer") {
    numeric_values <- suppressWarnings(as.numeric(x))
    converted <- as.integer(numeric_values)
    converted[!is.na(numeric_values) & numeric_values != trunc(numeric_values)] <- NA_integer_
  } else {
    normalized <- tolower(trimws(as.character(x)))
    converted <- rep(NA, length(x))
    converted[normalized %in% c("true", "1")] <- TRUE
    converted[normalized %in% c("false", "0")] <- FALSE
  }
  failed <- !missing & is.na(converted)
  if (invalid == "error" && any(failed)) stop("cast_invalid")
  converted[missing] <- NA
  converted
}
aur_terminology_map <- function(x, mappings, unmapped) {
  keys <- as.character(x)
  matched <- !is.na(keys) & keys %in% names(mappings)
  if (unmapped == "error" && any(!matched)) stop("terminology_mapping_unmapped")
  result <- unname(mappings[keys])
  if (unmapped == "preserve") result[!matched] <- x[!matched]
  result
}
.aur_vec <- function(fun, n, ...) {
  args <- list(...)
  out <- vector("list", n)
  for (i in seq_len(n)) {
    out[[i]] <- do.call(fun, lapply(args, function(a) a[[((i - 1) %% length(a)) + 1]]))
  }
  out
}
.aur_recycle <- function(..., n) {
  lapply(list(...), function(a) { if (length(a) == 1) rep(a, n) else a })
}
.aur_n <- function(...) max(vapply(list(...), length, integer(1)), 1L)
.aur_date <- function(x) {
  t <- .aur_txt(x)
  ok <- !is.na(t) & nchar(t) == 10 & substr(t, 5, 5) == "-" & substr(t, 8, 8) == "-"
  d <- rep(as.Date(NA), length(t))
  d[ok] <- as.Date(t[ok], format = "%Y-%m-%d")
  d
}
.aur_dt <- function(x) {
  t <- .aur_txt(x)
  t <- sub("[Zz]$", "", t)
  t <- gsub("T", " ", t)
  d <- as.POSIXct(t, format = "%Y-%m-%d %H:%M:%S", tz = "UTC")
  short <- is.na(d) & !is.na(t)
  if (any(short)) {
    d[short] <- as.POSIXct(t[short], format = "%Y-%m-%d %H:%M", tz = "UTC")
  }
  d
}
aur_concat <- function(...) {
  n <- .aur_n(...)
  parts <- lapply(list(...), function(a) {
    v <- .aur_txt(a); v[is.na(v)] <- ""; rep(v, length.out = n)
  })
  Reduce(function(x, y) paste0(x, y), parts)
}
aur_substring <- function(s, start, length) {
  n <- .aur_n(s, start, length)
  st <- .aur_txt(s); si <- .aur_int(start); ln <- .aur_int(length)
  r <- character(n)
  for (i in seq_len(n)) {
    ss <- st[[((i - 1) %% length(st)) + 1]]
    b <- max(si[[((i - 1) %% length(si)) + 1]], 1)
    l <- ln[[((i - 1) %% length(ln)) + 1]]
    if (is.na(ss)) { r[i] <- NA_character_ }
    else if (l <= 0) { r[i] <- "" }
    else { r[i] <- substr(ss, b, b + l - 1) }
  }
  r
}
aur_upper <- function(s) { v <- .aur_txt(s); ifelse(is.na(v), NA_character_, toupper(v)) }
aur_lower <- function(s) { v <- .aur_txt(s); ifelse(is.na(v), NA_character_, tolower(v)) }
aur_trim <- function(s) { v <- .aur_txt(s); ifelse(is.na(v), NA_character_, trimws(v)) }
aur_length <- function(s) { v <- .aur_txt(s); ifelse(is.na(v), NA_integer_, nchar(v)) }
aur_contains <- function(s, sub) {
  a <- .aur_txt(s); b <- .aur_txt(sub)
  ifelse(is.na(a) | is.na(b), NA, mapply(function(x, y) grepl(y, x, fixed = TRUE), a, b))
}
aur_startswith <- function(s, p) {
  a <- .aur_txt(s); b <- .aur_txt(p)
  ifelse(is.na(a) | is.na(b), NA, startsWith(a, b))
}
aur_endswith <- function(s, p) {
  a <- .aur_txt(s); b <- .aur_txt(p)
  ifelse(is.na(a) | is.na(b), NA, endsWith(a, b))
}
aur_replace <- function(s, find, repl) {
  a <- .aur_txt(s); f <- .aur_txt(find); w <- .aur_txt(repl)
  if (any(!is.na(f) & f == "")) stop("replace_empty_find")
  ifelse(is.na(a), NA_character_, mapply(function(x, y, z) gsub(y, z, x, fixed = TRUE), a, f, w))
}
aur_index_of <- function(s, sub) {
  a <- .aur_txt(s); b <- .aur_txt(sub)
  ifelse(is.na(a) | is.na(b), NA_integer_, {
    find1 <- function(x, y) { r <- regexpr(y, x, fixed = TRUE)[1]; if (r < 0) 0L else r }
    as.integer(mapply(find1, a, b))
  })
}
aur_scan_token <- function(s, idx, delim) {
  a <- .aur_txt(s); p <- .aur_int(idx); d <- .aur_txt(delim)
  if (any(!is.na(d) & d == "")) stop("scan_token_empty_delimiter")
  n <- .aur_n(a, p, d)
  r <- character(n)
  for (i in seq_len(n)) {
    av <- a[[((i - 1) %% length(a)) + 1]]
    dv <- d[[((i - 1) %% length(d)) + 1]]
    pv <- p[[((i - 1) %% length(p)) + 1]]
    if (is.na(av)) { r[i] <- NA_character_; next }
    toks <- strsplit(av, dv, fixed = TRUE)[[1]]
    toks <- toks[toks != ""]
    r[i] <- if (pv < 1 || pv > length(toks)) NA_character_ else toks[pv]
  }
  r
}
aur_pad_left <- function(s, w, f) {
  a <- .aur_txt(s); wi <- .aur_int(w); fc <- .aur_txt(f)
  if (any(!is.na(fc) & nchar(fc) != 1)) stop("pad_fill_not_single")
  n <- .aur_n(a, wi, fc)
  r <- character(n)
  for (i in seq_len(n)) {
    av <- a[[((i - 1) %% length(a)) + 1]]
    if (is.na(av)) { r[i] <- NA_character_; next }
    width <- wi[[((i - 1) %% length(wi)) + 1]]
    fill <- fc[[((i - 1) %% length(fc)) + 1]]
    if (nchar(av) >= width) { r[i] <- av } else {
      r[i] <- paste0(paste(rep(fill, width - nchar(av)), collapse = ""), av)
    }
  }
  r
}
aur_pad_right <- function(s, w, f) {
  a <- .aur_txt(s); wi <- .aur_int(w); fc <- .aur_txt(f)
  if (any(!is.na(fc) & nchar(fc) != 1)) stop("pad_fill_not_single")
  n <- .aur_n(a, wi, fc)
  r <- character(n)
  for (i in seq_len(n)) {
    av <- a[[((i - 1) %% length(a)) + 1]]
    if (is.na(av)) { r[i] <- NA_character_; next }
    width <- wi[[((i - 1) %% length(wi)) + 1]]
    fill <- fc[[((i - 1) %% length(fc)) + 1]]
    if (nchar(av) >= width) { r[i] <- av } else {
      r[i] <- paste0(av, paste(rep(fill, width - nchar(av)), collapse = ""))
    }
  }
  r
}
aur_coalesce <- function(...) {
  args <- list(...); n <- .aur_n(...)
  r <- rep(NA, n); r <- as.vector(r, mode = "list")
  for (i in seq_len(n)) {
    val <- NA
    for (a in args) { v <- a[[((i - 1) %% length(a)) + 1]]; if (!is.na(v)) { val <- v; break } }
    r[[i]] <- val
  }
  unlist(lapply(r, function(x) if (is.null(x)) NA else x))
}
aur_nullif <- function(a, b) {
  n <- .aur_n(a, b); r <- a[rep(seq_along(a), length.out = n)]
  bb <- b[rep(seq_along(b), length.out = n)]
  r[!is.na(r) & !is.na(bb) & r == bb] <- NA
  r
}
aur_is_in <- function(value, candidates) {
  cand <- unlist(candidates)
  ifelse(is.na(value), FALSE, value %in% cand)
}
aur_n_missing <- function(...) {
  args <- list(...); n <- .aur_n(...)
  r <- integer(n)
  for (i in seq_len(n)) {
    r[i] <- sum(vapply(args, function(a) is.na(a[[((i - 1) %% length(a)) + 1]]), logical(1)))
  }
  r
}
aur_n_present <- function(...) {
  args <- list(...); n <- .aur_n(...)
  r <- integer(n)
  for (i in seq_len(n)) {
    r[i] <- sum(vapply(args, function(a) !is.na(a[[((i - 1) %% length(a)) + 1]]), logical(1)))
  }
  r
}
aur_round <- function(x, digits) {
  xv <- .aur_num(x); dv <- .aur_int(digits)
  factor <- 10 ^ dv
  scaled <- xv * factor
  base <- floor(scaled)
  rem <- scaled - base
  up <- ifelse(rem > 0.5, base + 1, ifelse(rem < 0.5, base, ifelse(scaled >= 0, base + 1, base)))
  ifelse(is.na(xv) | is.na(dv), NA_real_, up / factor)
}
aur_floor <- function(x) { v <- .aur_num(x); ifelse(is.na(v), NA_integer_, as.integer(floor(v))) }
aur_ceil <- function(x) { v <- .aur_num(x); ifelse(is.na(v), NA_integer_, as.integer(ceiling(v))) }
aur_abs <- function(x) { v <- .aur_num(x); ifelse(is.na(v), NA_real_, abs(v)) }
aur_modulo <- function(a, b) {
  av <- .aur_int(a); bv <- .aur_int(b)
  ifelse(is.na(av) | is.na(bv) | bv == 0, NA_integer_, as.integer(av - bv * trunc(av / bv)))
}
aur_min_of <- function(...) {
  args <- lapply(list(...), .aur_num); n <- max(vapply(args, length, integer(1)), 1L)
  m <- do.call(pmin, c(lapply(args, function(a) rep(a, length.out = n)), na.rm = TRUE))
  m[is.infinite(m)] <- NA
  m
}
aur_max_of <- function(...) {
  args <- lapply(list(...), .aur_num); n <- max(vapply(args, length, integer(1)), 1L)
  m <- do.call(pmax, c(lapply(args, function(a) rep(a, length.out = n)), na.rm = TRUE))
  m[is.infinite(m)] <- NA
  m
}
aur_truncate <- function(x) {
  v <- .aur_num(x); ifelse(is.na(v), NA_integer_, as.integer(trunc(v)))
}
aur_safe_divide <- function(a, b) {
  av <- .aur_num(a); bv <- .aur_num(b)
  ifelse(is.na(av) | is.na(bv) | bv == 0, NA_real_, av / bv)
}
aur_parse_date <- function(x) format(.aur_date(x), "%Y-%m-%d")
aur_year <- function(x) {
  d <- .aur_date(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%Y")))
}
aur_month <- function(x) {
  d <- .aur_date(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%m")))
}
aur_day <- function(x) {
  d <- .aur_date(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%d")))
}
aur_date_diff_days <- function(e, s) {
  ed <- .aur_date(e); sd <- .aur_date(s)
  ifelse(is.na(ed) | is.na(sd), NA_integer_, as.integer(ed - sd))
}
aur_parse_datetime <- function(x) {
  d <- .aur_dt(x); ifelse(is.na(d), NA_character_, format(d, "%Y-%m-%d %H:%M:%S", tz = "UTC"))
}
aur_hour <- function(x) {
  d <- .aur_dt(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%H", tz = "UTC")))
}
aur_minute <- function(x) {
  d <- .aur_dt(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%M", tz = "UTC")))
}
aur_second <- function(x) {
  d <- .aur_dt(x); ifelse(is.na(d), NA_integer_, as.integer(format(d, "%S", tz = "UTC")))
}
aur_study_day <- function(e, r) {
  ed <- .aur_date(e); rd <- .aur_date(r)
  delta <- as.integer(ed - rd)
  ifelse(is.na(ed) | is.na(rd), NA_integer_, ifelse(delta >= 0, delta + 1L, delta))
}
aur_date_add_days <- function(b, n) {
  bd <- .aur_date(b); nn <- .aur_int(n)
  ifelse(is.na(bd) | is.na(nn), NA_character_, format(bd + nn, "%Y-%m-%d"))
}
aur_date_diff_months <- function(e, s) {
  ed <- .aur_date(e); sd <- .aur_date(s)
  n <- .aur_n(ed, sd); r <- integer(n)
  for (i in seq_len(n)) {
    a <- ed[[((i - 1) %% length(ed)) + 1]]; b <- sd[[((i - 1) %% length(sd)) + 1]]
    if (is.na(a) || is.na(b)) { r[i] <- NA_integer_; next }
    m <- (as.integer(format(a, "%Y")) - as.integer(format(b, "%Y"))) * 12 +
         (as.integer(format(a, "%m")) - as.integer(format(b, "%m")))
    da <- as.integer(format(a, "%d")); db <- as.integer(format(b, "%d"))
    if (m >= 0) { if (da < db) m <- m - 1 } else { if (da > db) m <- m + 1 }
    r[i] <- as.integer(m)
  }
  r
}
""".strip("\n")


def r_source(value: DataflowIR, digest: str) -> str:
    lines = [
        f"# aurinara-dataflow compiler=1.8.0 ir={digest}",
        'root <- Sys.getenv("AURINARA_WORKSPACE", unset = "/workspace")',
        'inputs <- file.path(root, "inputs")',
        'outputs <- file.path(root, "outputs")',
        "dir.create(outputs, recursive=TRUE, showWarnings=FALSE)",
        "bind_rows <- function(frames) {",
        "  columns <- unique(unlist(lapply(frames, names), use.names=FALSE))",
        "  normalized <- lapply(frames, function(frame) {",
        "    for (column in setdiff(columns, names(frame))) frame[[column]] <- NA",
        "    frame[, columns, drop=FALSE]",
        "  })",
        "  result <- do.call(rbind, normalized)",
        "  row.names(result) <- NULL",
        "  result",
        "}",
        _R_FUNCTION_PREAMBLE,
        _r_custom_functions(value.custom_functions),
        "state <- list()",
    ]
    incoming = incoming_nodes(value)
    for node in ordered_nodes(value):
        target = _rq(node.id)
        if node.node_type == "read":
            lines.append(
                f"state[[{target}]] <- read.csv(file.path(inputs, "
                f"{_rq(node.dataset + '.csv')}), check.names=FALSE, "
                'stringsAsFactors=FALSE, colClasses="character")'
            )
            continue
        if node.node_type == "union":
            refs = ", ".join(f"state[[{_rq(item)}]]" for item in incoming[node.id])
            lines.append(f"state[[{target}]] <- bind_rows(list({refs}))")
            continue
        if node.node_type == "join":
            left_keys = ", ".join(_rq(pair[0]) for pair in node.keys)
            right_keys = ", ".join(_rq(pair[1]) for pair in node.keys)
            all_left = "TRUE" if node.join_type in {"left", "full"} else "FALSE"
            all_right = "TRUE" if node.join_type in {"right", "full"} else "FALSE"
            lines.append(
                f"state[[{target}]] <- merge(state[[{_rq(node.left_input)}]], "
                f"state[[{_rq(node.right_input)}]], by.x=c({left_keys}), "
                f"by.y=c({right_keys}), all.x={all_left}, all.y={all_right}, "
                f"sort=FALSE, suffixes=c('', {_rq(node.right_suffix)}), incomparables=NA)"
            )
            continue
        source = f"state[[{_rq(_single(node, incoming[node.id]))}]]"
        if node.node_type == "select":
            lines.append(
                f"state[[{target}]] <- {source}[, c("
                f"{', '.join(_rq(x) for x in node.columns)}), drop=FALSE]"
            )
        elif node.node_type == "filter":
            lines.extend(
                [
                    f"frame <- {source}",
                    f"keep <- {_r_expr(node.predicate)}",
                    "keep[is.na(keep)] <- FALSE",
                    f"state[[{target}]] <- frame[keep, , drop=FALSE]",
                ]
            )
        elif node.node_type == "derive":
            lines.extend([f"frame <- {source}", "derived <- list()"])
            lines.extend(
                f"derived[[{_rq(name)}]] <- {_r_expr(expr)}"
                for name, expr in node.ordered_assignments()
            )
            lines.extend(
                f"frame[[{_rq(name)}]] <- derived[[{_rq(name)}]]"
                for name, _ in node.ordered_assignments()
            )
            lines.append(f"state[[{target}]] <- frame")
        elif node.node_type == "cast":
            lines.append(f"frame <- {source}")
            for name, operation in node.casts.items():
                source_values = f"frame[[{_rq(operation.source_column)}]]"
                lines.append(f"raw_values <- {source_values}")
                if operation.target_type == "text":
                    lines.append("converted <- as.character(raw_values)")
                    invalid = "rep(FALSE, length(raw_values))"
                elif operation.target_type == "float":
                    lines.append("converted <- suppressWarnings(as.numeric(raw_values))")
                    invalid = "!is.na(raw_values) & raw_values != '' & is.na(converted)"
                elif operation.target_type == "integer":
                    lines.extend(
                        [
                            "numeric_values <- suppressWarnings(as.numeric(raw_values))",
                            "converted <- as.integer(numeric_values)",
                        ]
                    )
                    invalid = (
                        "!is.na(raw_values) & raw_values != '' & "
                        "(is.na(numeric_values) | numeric_values != trunc(numeric_values))"
                    )
                else:
                    lines.extend(
                        [
                            "normalized <- tolower(trimws(as.character(raw_values)))",
                            "converted <- rep(NA, length(raw_values))",
                            "converted[normalized %in% c('true', '1')] <- TRUE",
                            "converted[normalized %in% c('false', '0')] <- FALSE",
                        ]
                    )
                    invalid = (
                        "!is.na(raw_values) & raw_values != '' & "
                        "!normalized %in% c('true', '1', 'false', '0')"
                    )
                if operation.invalid == "error":
                    lines.append(f"if (any({invalid})) stop('cast_invalid')")
                lines.append(f"frame[[{_rq(name)}]] <- converted")
            lines.append(f"state[[{target}]] <- frame")
        elif node.node_type == "aggregate":
            lines.append(f"frame <- {source}")
            if node.group_by:
                group_refs = ", ".join(_rq(name) for name in node.group_by)
                lines.extend(
                    [
                        f"groups <- unique(frame[, c({group_refs}), drop=FALSE])",
                        "result <- groups",
                    ]
                )
                mask = " & ".join(
                    f"frame[[{_rq(name)}]] == groups[[{_rq(name)}]][i]" for name in node.group_by
                )
                lines.append("for (i in seq_len(nrow(groups))) {")
                lines.append(f"  members <- frame[{mask}, , drop=FALSE]")
                indent = "  "
            else:
                lines.extend(["result <- data.frame(row.names=1)", "members <- frame"])
                indent = ""
            for name, spec in node.aggregations.items():
                if spec.operation == "count" and spec.column is None:
                    expression = "nrow(members)"
                else:
                    assert spec.column is not None
                    raw_values = f"members[[{_rq(spec.column)}]]"
                    if spec.operation == "count":
                        expression = f"sum(!is.na({raw_values}) & {raw_values} != '')"
                    elif spec.operation == "mean":
                        values = f"as.numeric({raw_values})"
                        expression = f"if (all(is.na({values}))) NA else mean({values}, na.rm=TRUE)"
                    else:
                        values = f"as.numeric({raw_values})"
                        expression = (
                            f"if (all(is.na({values}))) NA else "
                            f"{spec.operation}({values}, na.rm=TRUE)"
                        )
                if node.group_by:
                    lines.append(f"{indent}result[[{_rq(name)}]][i] <- {expression}")
                else:
                    lines.append(f"result[[{_rq(name)}]] <- {expression}")
            if node.group_by:
                lines.append("}")
            lines.append(f"state[[{target}]] <- result")
        elif node.node_type == "pivot_longer":
            id_refs = ", ".join(_rq(name) for name in node.id_columns)
            value_refs = ", ".join(_rq(name) for name in node.value_columns)
            lines.extend(
                [
                    f"frame <- {source}",
                    f"pieces <- lapply(c({value_refs}), function(column) {{",
                    (
                        f"  item <- frame[, c({id_refs}), drop=FALSE]"
                        if node.id_columns
                        else "  item <- data.frame(row.names=seq_len(nrow(frame)))"
                    ),
                    f"  item[[{_rq(node.name_column)}]] <- column",
                    f"  item[[{_rq(node.value_column)}]] <- frame[[column]]",
                    "  item",
                    "})",
                    f"state[[{target}]] <- do.call(rbind, pieces)",
                    f"row.names(state[[{target}]]) <- NULL",
                ]
            )
        elif node.node_type == "terminology_map":
            mapping_keys = ", ".join(_rq(key) for key in node.mappings)
            mapping_values = ", ".join(_rq(value) for value in node.mappings.values())
            lines.extend(
                [
                    f"frame <- {source}",
                    f"mapping <- setNames(c({mapping_values}), c({mapping_keys}))",
                    f"source_values <- frame[[{_rq(node.source_column)}]]",
                    "mapped <- unname(mapping[source_values])",
                ]
            )
            if node.unmapped == "error":
                lines.append("if (any(is.na(mapped))) stop('terminology_mapping_unmapped')")
            elif node.unmapped == "preserve":
                lines.append("mapped[is.na(mapped)] <- source_values[is.na(mapped)]")
            lines.extend(
                [
                    f"frame[[{_rq(node.target_column)}]] <- mapped",
                    f"state[[{target}]] <- frame",
                ]
            )
        elif node.node_type == "sequence":
            sequence_keys = (*node.group_by, *node.order_by)
            order_values = ", ".join(f"frame[[{_rq(name)}]]" for name in sequence_keys)
            lines.extend(
                [
                    f"frame <- {source}",
                    f"frame <- frame[do.call(order, list({order_values}, na.last=TRUE)), "
                    ", drop=FALSE]",
                ]
            )
            if node.group_by:
                group_refs = ", ".join(_rq(name) for name in node.group_by)
                lines.extend(
                    [
                        f"group_key <- interaction(frame[, c({group_refs}), drop=FALSE], "
                        "drop=TRUE, lex.order=TRUE)",
                        f"frame[[{_rq(node.target_column)}]] <- "
                        f"ave(seq_len(nrow(frame)), group_key, FUN=seq_along) + {node.start - 1}",
                    ]
                )
            else:
                lines.append(
                    f"frame[[{_rq(node.target_column)}]] <- seq_len(nrow(frame)) + {node.start - 1}"
                )
            lines.append(f"state[[{target}]] <- frame")
        elif node.node_type == "window":
            window_keys = (*node.partition_by, *node.order_by)
            order_values = ", ".join(f"frame[[{_rq(name)}]]" for name in window_keys)
            lines.extend(
                [
                    f"frame <- {source}",
                    f"frame <- frame[do.call(order, list({order_values}, na.last=TRUE)), "
                    ", drop=FALSE]",
                ]
            )
            if node.partition_by:
                partition_refs = ", ".join(_rq(name) for name in node.partition_by)
                lines.extend(
                    [
                        f"partition_key <- interaction(frame[, c({partition_refs}), drop=FALSE], "
                        "drop=TRUE, lex.order=TRUE)",
                        "group_indices <- split(seq_len(nrow(frame)), partition_key, drop=TRUE)",
                    ]
                )
            else:
                lines.append("group_indices <- list(seq_len(nrow(frame)))")
            for name, window_operation in node.operations.items():
                target_ref = _rq(name)
                if window_operation.operation == "row_number":
                    lines.extend(
                        [
                            "window_output <- rep(NA_integer_, nrow(frame))",
                            "for (indices in group_indices) {",
                            "  window_output[indices] <- seq_along(indices)",
                            "}",
                        ]
                    )
                elif window_operation.operation == "lag":
                    assert window_operation.source_column is not None
                    lines.extend(
                        [
                            f"window_source <- frame[[{_rq(window_operation.source_column)}]]",
                            "window_output <- rep(NA, nrow(frame))",
                            "for (indices in group_indices) {",
                            f"  if (length(indices) > {window_operation.offset}) {{",
                            "    targets <- indices[("
                            f"{window_operation.offset} + 1):length(indices)]",
                            "    sources <- indices[1:(length(indices) - "
                            f"{window_operation.offset})]",
                            "    window_output[targets] <- window_source[sources]",
                            "  }",
                            "}",
                        ]
                    )
                else:
                    assert window_operation.source_column is not None
                    lines.extend(
                        [
                            f"raw_window <- frame[[{_rq(window_operation.source_column)}]]",
                            "window_source <- suppressWarnings(as.numeric(raw_window))",
                            "invalid_window <- !is.na(raw_window) & raw_window != '' & "
                            "is.na(window_source)",
                            "if (any(invalid_window)) stop('window_numeric_invalid')",
                            "window_output <- rep(NA_real_, nrow(frame))",
                            "for (indices in group_indices) {",
                            "  running <- 0",
                            "  for (index in indices) {",
                            "    if (!is.na(window_source[index])) {",
                            "      running <- running + window_source[index]",
                            "      window_output[index] <- running",
                            "    }",
                            "  }",
                            "}",
                        ]
                    )
                lines.append(f"frame[[{target_ref}]] <- window_output")
            lines.append(f"state[[{target}]] <- frame")
        elif node.node_type == "sort":
            sort_columns = ", ".join(f"{source}[[{_rq(x)}]]" for x in node.keys)
            lines.append(
                f"state[[{target}]] <- {source}[do.call(order, list({sort_columns})), , drop=FALSE]"
            )
        elif node.node_type == "assert":
            lines.extend(
                [
                    f"frame <- {source}",
                    f"if (!all({_r_expr(node.predicate)}, na.rm=FALSE)) "
                    f"stop({_rq(node.issue_code)})",
                    f"state[[{target}]] <- frame",
                ]
            )
        elif node.node_type == "write":
            lines.extend(
                [
                    f"state[[{target}]] <- {source}",
                    f"write.csv(state[[{target}]], file.path(outputs, "
                    f'{_rq(node.dataset + ".csv")}), row.names=FALSE, na="")',
                ]
            )
        else:
            raise UnsupportedOperator(node.node_type)
    return "\n".join(lines) + "\n"
