"""Catalog function semantics shared by the preview evaluator.

This module is the single Python reference implementation of the typed
function catalog (design §4.3 + §4.6) under the ratified decisions D3-D11.
The preview evaluator dispatches scalar arguments through :data:`REGISTRY`;
the Python code generator emits standalone equivalents of the same semantics
so that preview and compiled output agree.

Every function receives already-evaluated scalar arguments. Null is modelled
as ``None``. ``_Invalid`` is raised for argument-type problems so the
evaluator can translate it to a 422 problem; by contract (null-in -> null-out)
most type mismatches never reach that path, but defensive guards remain.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta

Scalar = object | None


class ExpressionFunctionError(ValueError):
    """Raised when a function argument is structurally invalid.

    ``code`` is a stable preview problem code the evaluator maps to a 422.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _invalid(detail: str) -> ExpressionFunctionError:
    return ExpressionFunctionError("preview_function_argument_invalid", detail)


def _date_invalid(detail: str) -> ExpressionFunctionError:
    return ExpressionFunctionError("preview_date_parse_invalid", detail)


# --- numeric helpers (D3) ----------------------------------------------------


def half_away_round(value: float, digits: int) -> float:
    """Round half away from zero to ``digits`` decimal places (D3)."""

    factor = 10.0**digits
    scaled = value * factor
    floor_value = math.floor(scaled)
    remainder = scaled - floor_value
    if remainder > 0.5:
        rounded = floor_value + 1
    elif remainder < 0.5:
        rounded = floor_value
    else:
        rounded = floor_value + 1 if scaled >= 0 else floor_value
    return rounded / factor


def truncated_modulo(dividend: float, divisor: float) -> float:
    """Modulo whose sign follows the dividend (truncated division, D3)."""

    return dividend - divisor * math.trunc(dividend / divisor)


def _as_number(value: Scalar) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError as error:
            raise _invalid(f"'{value}' is not numeric") from error
    raise _invalid(f"'{value!r}' is not numeric")


def _as_int(value: Scalar, *, label: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError as error:
            raise _invalid(f"{label} must be an integer, got '{value}'") from error
    raise _invalid(f"{label} must be an integer")


def _as_text(value: Scalar) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    raise _invalid(f"'{value!r}' is not a string")


# --- date helpers (D4, D8, D9, D10) ------------------------------------------


def parse_full_date(value: Scalar) -> date | None:
    """Parse strict ``YYYY-MM-DD``; partial/invalid -> None (D4)."""

    if value is None:
        return None
    text = _as_text(value).strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_naive_datetime(value: Scalar) -> datetime | None:
    """Parse naive/UTC ISO 8601 datetime; offsets/partials -> None (D10)."""

    if value is None:
        return None
    text = _as_text(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1]
    normalized = text.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        return parsed
    return None


def _require_date(value: Scalar, func: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_full_date(value)
    if parsed is None:
        raise _date_invalid(f"{func} requires a parsed date")
    return parsed


def _require_datetime(value: Scalar, func: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    parsed = parse_naive_datetime(value)
    if parsed is None:
        raise _date_invalid(f"{func} requires a parsed datetime")
    return parsed


def study_day(event: Scalar, reference: Scalar) -> int | None:
    """CDISC ``--DY`` with no day zero (D8)."""

    event_date = _require_date(event, "study_day")
    reference_date = _require_date(reference, "study_day")
    if event_date is None or reference_date is None:
        return None
    delta = (event_date - reference_date).days
    return delta + 1 if delta >= 0 else delta


def date_diff_months(end: Scalar, start: Scalar) -> int | None:
    """Continuous whole-month difference, day-of-month aware (D9)."""

    end_date = _require_date(end, "date_diff_months")
    start_date = _require_date(start, "date_diff_months")
    if end_date is None or start_date is None:
        return None
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    if months >= 0:
        if end_date.day < start_date.day:
            months -= 1
    else:
        if end_date.day > start_date.day:
            months += 1
    return months


# --- string helpers (D5, D7) -------------------------------------------------


def _ascii_upper(value: str) -> str:
    return value.translate(_ASCII_UPPER)


def _ascii_lower(value: str) -> str:
    return value.translate(_ASCII_LOWER)


_ASCII_UPPER = {code: code - 32 for code in range(ord("a"), ord("z") + 1)}
_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}


def scan_token(value: Scalar, index: Scalar, delimiter: Scalar) -> str | None:
    """1-based token with consecutive-delimiter collapse (D7)."""

    if value is None:
        return None
    text = _as_text(value)
    position = _as_int(index, label="scan_token index")
    delim = _as_text(delimiter)
    if delim == "":
        raise _invalid("scan_token delimiter must be non-empty")
    tokens = [token for token in text.split(delim) if token != ""]
    if position < 1 or position > len(tokens):
        return None
    return tokens[position - 1]


# --- function implementations ------------------------------------------------


def _concat(args: Sequence[Scalar]) -> str:
    return "".join("" if value is None else _as_text(value) for value in args)


def _substring(args: Sequence[Scalar]) -> str | None:
    source, start, length = args
    if source is None:
        return None
    text = _as_text(source)
    start_index = _as_int(start, label="substring start")
    span = _as_int(length, label="substring length")
    begin = max(start_index - 1, 0)
    if span <= 0:
        return ""
    return text[begin : begin + span]


def _upper(args: Sequence[Scalar]) -> str | None:
    (source,) = args
    return None if source is None else _ascii_upper(_as_text(source))


def _lower(args: Sequence[Scalar]) -> str | None:
    (source,) = args
    return None if source is None else _ascii_lower(_as_text(source))


def _trim(args: Sequence[Scalar]) -> str | None:
    (source,) = args
    return None if source is None else _as_text(source).strip()


def _length(args: Sequence[Scalar]) -> int | None:
    (source,) = args
    return None if source is None else len(_as_text(source))


def _contains(args: Sequence[Scalar]) -> bool | None:
    source, needle = args
    if source is None or needle is None:
        return None
    return _as_text(needle) in _as_text(source)


def _startswith(args: Sequence[Scalar]) -> bool | None:
    source, prefix = args
    if source is None or prefix is None:
        return None
    return _as_text(source).startswith(_as_text(prefix))


def _endswith(args: Sequence[Scalar]) -> bool | None:
    source, suffix = args
    if source is None or suffix is None:
        return None
    return _as_text(source).endswith(_as_text(suffix))


def _replace(args: Sequence[Scalar]) -> str | None:
    source, find, replacement = args
    if source is None:
        return None
    find_text = _as_text(find)
    if find_text == "":
        raise _invalid("replace find must be non-empty")
    return _as_text(source).replace(find_text, _as_text(replacement))


def _index_of(args: Sequence[Scalar]) -> int | None:
    source, needle = args
    if source is None or needle is None:
        return None
    return _as_text(source).find(_as_text(needle)) + 1


def _scan_token(args: Sequence[Scalar]) -> str | None:
    source, index, delimiter = args
    return scan_token(source, index, delimiter)


def _pad(args: Sequence[Scalar], *, left: bool) -> str | None:
    source, width, fill = args
    if source is None:
        return None
    text = _as_text(source)
    target_width = _as_int(width, label="pad width")
    fill_char = _as_text(fill)
    if len(fill_char) != 1:
        raise _invalid("pad fill must be exactly one character")
    return text.rjust(target_width, fill_char) if left else text.ljust(target_width, fill_char)


def _pad_left(args: Sequence[Scalar]) -> str | None:
    return _pad(args, left=True)


def _pad_right(args: Sequence[Scalar]) -> str | None:
    return _pad(args, left=False)


def _coalesce(args: Sequence[Scalar]) -> Scalar:
    for value in args:
        if value is not None:
            return value
    return None


def _nullif(args: Sequence[Scalar]) -> Scalar:
    first, second = args
    if first is None:
        return None
    return None if first == second else first


def _is_in(args: Sequence[Scalar]) -> bool | None:
    value, candidates = args
    if value is None:
        return False
    if not isinstance(candidates, tuple):
        raise _invalid("is_in requires a list literal as its second argument")
    return value in candidates


def _n_missing(args: Sequence[Scalar]) -> int:
    return sum(1 for value in args if value is None)


def _n_present(args: Sequence[Scalar]) -> int:
    return sum(1 for value in args if value is not None)


def _round(args: Sequence[Scalar]) -> float | None:
    value, digits = args
    if value is None or digits is None:
        return None
    return half_away_round(_as_number(value), _as_int(digits, label="round digits"))


def _floor(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    return None if value is None else math.floor(_as_number(value))


def _ceil(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    return None if value is None else math.ceil(_as_number(value))


def _abs(args: Sequence[Scalar]) -> Scalar:
    (value,) = args
    if value is None:
        return None
    if isinstance(value, bool):
        return abs(int(value))
    if isinstance(value, int):
        return abs(value)
    return abs(_as_number(value))


def _modulo(args: Sequence[Scalar]) -> int | None:
    first, second = args
    if first is None or second is None:
        return None
    dividend = _as_int(first, label="modulo dividend")
    divisor = _as_int(second, label="modulo divisor")
    if divisor == 0:
        return None
    return int(truncated_modulo(dividend, divisor))


def _min_of(args: Sequence[Scalar]) -> Scalar:
    present = [value for value in args if value is not None]
    if not present:
        return None
    return min(present, key=_sort_key)


def _max_of(args: Sequence[Scalar]) -> Scalar:
    present = [value for value in args if value is not None]
    if not present:
        return None
    return max(present, key=_sort_key)


def _sort_key(value: Scalar) -> tuple[int, float, str]:
    if isinstance(value, bool):
        return (0, float(value), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0.0, _as_text(value))


def _truncate(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    return None if value is None else math.trunc(_as_number(value))


def _safe_divide(args: Sequence[Scalar]) -> float | None:
    first, second = args
    if first is None or second is None:
        return None
    divisor = _as_number(second)
    if divisor == 0:
        return None
    return _as_number(first) / divisor


def _parse_date(args: Sequence[Scalar]) -> date | None:
    (value,) = args
    return parse_full_date(value)


def _year(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    parsed = _require_date(value, "year")
    return None if parsed is None else parsed.year


def _month(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    parsed = _require_date(value, "month")
    return None if parsed is None else parsed.month


def _day(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    parsed = _require_date(value, "day")
    return None if parsed is None else parsed.day


def _date_diff_days(args: Sequence[Scalar]) -> int | None:
    end, start = args
    end_date = _require_date(end, "date_diff_days")
    start_date = _require_date(start, "date_diff_days")
    if end_date is None or start_date is None:
        return None
    return (end_date - start_date).days


def _parse_datetime(args: Sequence[Scalar]) -> datetime | None:
    (value,) = args
    return parse_naive_datetime(value)


def _hour(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    parsed = _require_datetime(value, "hour")
    return None if parsed is None else parsed.hour


def _minute(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    parsed = _require_datetime(value, "minute")
    return None if parsed is None else parsed.minute


def _second(args: Sequence[Scalar]) -> int | None:
    (value,) = args
    parsed = _require_datetime(value, "second")
    return None if parsed is None else parsed.second


def _study_day(args: Sequence[Scalar]) -> int | None:
    event, reference = args
    return study_day(event, reference)


def _date_add_days(args: Sequence[Scalar]) -> date | None:
    base, offset = args
    base_date = _require_date(base, "date_add_days")
    if base_date is None or offset is None:
        return None
    return base_date + timedelta(days=_as_int(offset, label="date_add_days n"))


def _date_diff_months(args: Sequence[Scalar]) -> int | None:
    end, start = args
    return date_diff_months(end, start)


REGISTRY: dict[str, Callable[[Sequence[Scalar]], Scalar]] = {
    "concat": _concat,
    "substring": _substring,
    "upper": _upper,
    "lower": _lower,
    "trim": _trim,
    "length": _length,
    "contains": _contains,
    "startswith": _startswith,
    "endswith": _endswith,
    "replace": _replace,
    "index_of": _index_of,
    "scan_token": _scan_token,
    "pad_left": _pad_left,
    "pad_right": _pad_right,
    "coalesce": _coalesce,
    "nullif": _nullif,
    "is_in": _is_in,
    "n_missing": _n_missing,
    "n_present": _n_present,
    "round": _round,
    "floor": _floor,
    "ceil": _ceil,
    "abs": _abs,
    "modulo": _modulo,
    "min_of": _min_of,
    "max_of": _max_of,
    "truncate": _truncate,
    "safe_divide": _safe_divide,
    "parse_date": _parse_date,
    "year": _year,
    "month": _month,
    "day": _day,
    "date_diff_days": _date_diff_days,
    "parse_datetime": _parse_datetime,
    "hour": _hour,
    "minute": _minute,
    "second": _second,
    "study_day": _study_day,
    "date_add_days": _date_add_days,
    "date_diff_months": _date_diff_months,
}
