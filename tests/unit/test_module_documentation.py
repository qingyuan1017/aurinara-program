"""Keep current module usage guides aligned with registered module keys."""

import re
from pathlib import Path

from app.composition import BUILTIN_DESCRIPTORS

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_DOCS = REPOSITORY_ROOT / "docs" / "modules"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\((?!https?://|#)([^)]+)\)")


def test_every_registered_module_has_a_usage_guide() -> None:
    """A newly registered module must declare its current usable surface."""

    missing = [
        descriptor.module_key
        for descriptor in BUILTIN_DESCRIPTORS
        if not (MODULE_DOCS / f"{descriptor.module_key}.md").is_file()
    ]
    assert missing == []


def test_module_guide_local_links_resolve() -> None:
    """Relative links in the guide set should not silently decay."""

    broken: list[str] = []
    for document in MODULE_DOCS.glob("*.md"):
        content = document.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(content):
            path_text = target.split("#", maxsplit=1)[0]
            if path_text and not (document.parent / path_text).resolve().exists():
                broken.append(f"{document.name}: {target}")
    assert broken == []
