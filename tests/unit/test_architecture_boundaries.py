"""Static checks for modular-monolith import ownership."""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "src" / "app"
CLINICAL_PACKAGES = frozenset({"raw", "documents", "sdtm", "adam", "tlf"})


def _app_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names if alias.name.startswith("app."))
    return tuple(imports)


def _package(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else None


def test_clinical_packages_do_not_import_each_other() -> None:
    violations: list[str] = []
    for owner in sorted(CLINICAL_PACKAGES):
        for path in sorted((APP_ROOT / owner).rglob("*.py")):
            for module in _app_imports(path):
                imported_owner = _package(module)
                if imported_owner in CLINICAL_PACKAGES and imported_owner != owner:
                    violations.append(f"{path.relative_to(APP_ROOT)} -> {module}")
    assert violations == []


def test_common_and_transformation_do_not_depend_on_clinical_packages() -> None:
    violations: list[str] = []
    for owner in ("common", "transformation"):
        for path in sorted((APP_ROOT / owner).rglob("*.py")):
            for module in _app_imports(path):
                if _package(module) in CLINICAL_PACKAGES:
                    violations.append(f"{path.relative_to(APP_ROOT)} -> {module}")
    assert violations == []


def test_transformation_has_no_transport_or_persistence_dependency() -> None:
    forbidden_prefixes = ("fastapi", "sqlalchemy", "app.database")
    violations: list[str] = []
    for path in sorted((APP_ROOT / "transformation").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = (node.module,)
            elif isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            for module in modules:
                if module.startswith(forbidden_prefixes):
                    violations.append(f"{path.relative_to(APP_ROOT)} -> {module}")
    assert violations == []
