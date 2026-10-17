"""Deterministic normalization for generated ZIP-based file formats."""

import io
import re
import zipfile


def normalize_zip_bytes(data: bytes) -> bytes:
    """Return stable ZIP bytes independent of host OS and generation time."""

    source = io.BytesIO(data)
    target = io.BytesIO()
    with (
        zipfile.ZipFile(source, "r") as reader,
        zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as writer,
    ):
        for name in sorted(reader.namelist()):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            member = reader.read(name)
            if name == "docProps/core.xml":
                member = re.sub(
                    rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                    rb"\g<1>2000-01-01T00:00:00Z\g<2>",
                    member,
                )
            writer.writestr(info, member)
    return target.getvalue()
