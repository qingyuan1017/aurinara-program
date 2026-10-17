"""Execution-worker behavior that does not require a runner or persistence."""

import pytest

from app.execution.worker import _prepare_test_preview


def test_workarea_test_preview_is_bounded_without_generation_validation() -> None:
    rows = "".join(f"{index},term {index}\n" for index in range(105))

    preview = _prepare_test_preview(
        {"AE.csv": f"AESEQ,AETERM\n{rows}".encode()},
        "AE",
        maximum_bytes=100_000,
    )

    assert len(preview) == 100
    assert preview[0] == {"AESEQ": "0", "AETERM": "term 0"}
    assert preview[-1] == {"AESEQ": "99", "AETERM": "term 99"}


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"DM.csv": b"USUBJID\n01\n"}, "exactly its own declared"),
        ({"AE.csv": b"AETERM,AETERM\na,b\n"}, "present and unique"),
        ({"AE.csv": b"AETERM\n\xff\n"}, "valid UTF-8"),
    ],
)
def test_workarea_test_preview_rejects_invalid_output_envelopes(
    files: dict[str, bytes], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _prepare_test_preview(files, "AE", maximum_bytes=100_000)
