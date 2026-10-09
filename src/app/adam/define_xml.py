"""Deterministic ADaM Define-XML 2.0/2.1 rendering over pinned local schemas."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from lxml import etree

from app.adam.contracts import AdamDefineModel, AdamOrigin, AdamValueLevelMetadata
from app.common.problems import ProblemException
from app.transformation.contracts import Expression

DefineXmlVersion = Literal["2.0", "2.1"]
ODM = "http://www.cdisc.org/ns/odm/v1.3"
XLINK = "http://www.w3.org/1999/xlink"
XML = "http://www.w3.org/XML/1998/namespace"
GENERATOR_VERSION = "1.1.0"
_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas" / "cdisc" / "define-xml"


def _q(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _description(parent: etree._Element, value: str) -> None:
    description = etree.SubElement(parent, _q(ODM, "Description"))
    translated = etree.SubElement(description, _q(ODM, "TranslatedText"))
    translated.set(_q(XML, "lang"), "en")
    translated.text = value


def _origin_text(origin: AdamOrigin) -> str | None:
    if origin.origin_type == "Predecessor":
        return f"{origin.source_kind}:{origin.source_dataset}.{origin.source_variable}"
    return origin.description


def _literal_text(value: str | int | float | bool | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _condition_checks(
    expression: Expression, dataset_code: str, known_variables: frozenset[str]
) -> tuple[tuple[str, str, str], ...] | None:
    """Lower the exact Define-representable subset of typed conditions to range checks."""

    if expression.kind != "binary":
        return None
    if expression.operator == "and":
        left = _condition_checks(expression.left, dataset_code, known_variables)
        right = _condition_checks(expression.right, dataset_code, known_variables)
        return (*left, *right) if left is not None and right is not None else None
    comparators = {"eq": "EQ", "ne": "NE", "lt": "LT", "le": "LE", "gt": "GT", "ge": "GE"}
    comparator = comparators.get(expression.operator)
    if comparator is None:
        return None
    column = expression.left
    literal = expression.right
    if column.kind == "literal" and literal.kind == "column":
        column, literal = literal, column
        comparator = {"LT": "GT", "LE": "GE", "GT": "LT", "GE": "LE"}.get(comparator, comparator)
    if (
        column.kind != "column"
        or literal.kind != "literal"
        or column.dataset != dataset_code
        or column.column not in known_variables
    ):
        return None
    value = _literal_text(literal.value)
    if value is None:
        return None
    return ((f"IT.{dataset_code}.{column.column}", comparator, value),)


def _formal_value_levels(
    model: AdamDefineModel,
) -> tuple[tuple[str, str, int, AdamValueLevelMetadata, tuple[tuple[str, str, str], ...]], ...]:
    values: list[
        tuple[str, str, int, AdamValueLevelMetadata, tuple[tuple[str, str, str], ...]]
    ] = []
    for dataset in model.datasets:
        known_variables = frozenset(variable.name for variable in dataset.variables)
        for order, value_level in enumerate(dataset.value_level_metadata, start=1):
            checks = _condition_checks(value_level.condition, dataset.code, known_variables)
            if checks is not None:
                values.append((dataset.code, value_level.variable, order, value_level, checks))
    return tuple(values)


def render_define_xml(model: AdamDefineModel, version: DefineXmlVersion) -> bytes:
    """Render deterministic ADaM Define XML and validate it before returning bytes."""

    def_ns = f"http://www.cdisc.org/ns/def/v{version}"
    root = etree.Element(
        _q(ODM, "ODM"),
        nsmap={None: ODM, "def": def_ns, "xlink": XLINK},  # type: ignore[dict-item]
        FileType="Snapshot",
        FileOID=f"ODM.{model.study_oid}",
        CreationDateTime="2000-01-01T00:00:00",
        Originator="Aurinara",
        SourceSystem="Aurinara",
        SourceSystemVersion=GENERATOR_VERSION,
    )
    if version == "2.1":
        root.set(_q(def_ns, "Context"), "Submission")
    study = etree.SubElement(root, _q(ODM, "Study"), OID=model.study_oid)
    global_variables = etree.SubElement(study, _q(ODM, "GlobalVariables"))
    for name, value in (
        ("StudyName", model.name),
        ("StudyDescription", model.description or model.name),
        ("ProtocolName", model.study_oid),
    ):
        etree.SubElement(global_variables, _q(ODM, name)).text = value
    attributes = {
        "OID": model.metadata_version_oid,
        "Name": model.name,
        _q(def_ns, "DefineVersion"): f"{version}.0",
    }
    if model.description is not None:
        attributes["Description"] = model.description
    if version == "2.0":
        attributes[_q(def_ns, "StandardName")] = model.standard_name
        attributes[_q(def_ns, "StandardVersion")] = model.standard_version
    metadata = etree.SubElement(study, _q(ODM, "MetaDataVersion"), attrib=attributes)
    if version == "2.1":
        standards = etree.SubElement(metadata, _q(def_ns, "Standards"))
        etree.SubElement(
            standards,
            _q(def_ns, "Standard"),
            OID="STD.1",
            Name=model.standard_name.replace("-", ""),
            Type="IG",
            Version=model.standard_version,
            Status="Final",
        )
    formal_value_levels = _formal_value_levels(model)
    grouped_value_levels: dict[
        tuple[str, str],
        list[tuple[int, AdamValueLevelMetadata, tuple[tuple[str, str, str], ...]]],
    ] = {}
    for dataset_code, variable_name, order, value_level, checks in formal_value_levels:
        grouped_value_levels.setdefault((dataset_code, variable_name), []).append(
            (order, value_level, checks)
        )
    for (dataset_code, variable_name), values in grouped_value_levels.items():
        value_list = etree.SubElement(
            metadata,
            _q(def_ns, "ValueListDef"),
            OID=f"VL.{dataset_code}.{variable_name}",
        )
        for order, value_level, _ in values:
            formal_ref_attributes = {
                "ItemOID": f"IT.{dataset_code}.{variable_name}.VL.{value_level.id.hex}",
                "OrderNumber": str(order),
                "Mandatory": "No",
            }
            if value_level.method_id is not None:
                formal_ref_attributes["MethodOID"] = value_level.method_id
            formal_item_ref = etree.SubElement(
                value_list, _q(ODM, "ItemRef"), attrib=formal_ref_attributes
            )
            etree.SubElement(
                formal_item_ref,
                _q(def_ns, "WhereClauseRef"),
                WhereClauseOID=f"WC.{value_level.id.hex}",
            )
    for _, _, _, value_level, checks in formal_value_levels:
        where_clause = etree.SubElement(
            metadata, _q(def_ns, "WhereClauseDef"), OID=f"WC.{value_level.id.hex}"
        )
        for item_oid, comparator, value in checks:
            range_check = etree.SubElement(
                where_clause,
                _q(ODM, "RangeCheck"),
                Comparator=comparator,
                SoftHard="Soft",
            )
            range_check.set(_q(def_ns, "ItemOID"), item_oid)
            etree.SubElement(range_check, _q(ODM, "CheckValue")).text = value
    leaves = {leaf.artifact_id: leaf for leaf in model.leaves}
    for dataset in model.datasets:
        leaf = next(
            (item for item in leaves.values() if item.href == dataset.expected_output_name), None
        )
        group_attributes = {
            "OID": f"IG.{dataset.code}",
            "Name": dataset.code,
            "Repeating": "Yes",
            "IsReferenceData": "No",
            "SASDatasetName": dataset.code,
            "Domain": dataset.code,
            "Purpose": "Analysis",
            _q(def_ns, "Structure"): dataset.structure,
        }
        if leaf is not None:
            group_attributes[_q(def_ns, "ArchiveLocationID")] = leaf.id
        if dataset.parameters:
            group_attributes[_q(def_ns, "CommentOID")] = f"COM.PARAM.{dataset.code}"
        if version == "2.0":
            group_attributes[_q(def_ns, "Class")] = dataset.dataset_class
        else:
            group_attributes[_q(def_ns, "StandardOID")] = "STD.1"
        group = etree.SubElement(metadata, _q(ODM, "ItemGroupDef"), attrib=group_attributes)
        _description(group, dataset.label)
        for order, variable in enumerate(dataset.variables, start=1):
            group_item_ref_attributes = {
                "ItemOID": f"IT.{dataset.code}.{variable.name}",
                "OrderNumber": str(order),
                "Mandatory": "Yes" if variable.name in dataset.keys else "No",
                "Role": variable.role,
            }
            if variable.method_id is not None:
                group_item_ref_attributes["MethodOID"] = variable.method_id
            etree.SubElement(group, _q(ODM, "ItemRef"), attrib=group_item_ref_attributes)
        if version == "2.1":
            etree.SubElement(group, _q(def_ns, "Class"), Name=dataset.dataset_class.upper())
    for dataset in model.datasets:
        known_variables = frozenset(variable.name for variable in dataset.variables)
        for variable in dataset.variables:
            item_attributes = {
                "OID": f"IT.{dataset.code}.{variable.name}",
                "Name": variable.name,
                "DataType": "text" if variable.data_type == "character" else "float",
            }
            if variable.length is not None:
                item_attributes["Length"] = str(variable.length)
            variable_value_levels = tuple(
                value for value in dataset.value_level_metadata if value.variable == variable.name
            )
            if variable_value_levels:
                item_attributes[_q(def_ns, "CommentOID")] = (
                    f"COM.VLM.{dataset.code}.{variable.name}"
                )
            item = etree.SubElement(metadata, _q(ODM, "ItemDef"), attrib=item_attributes)
            _description(item, variable.label)
            if variable.terminology_binding is not None:
                binding = variable.terminology_binding
                etree.SubElement(
                    item,
                    _q(ODM, "Alias"),
                    Context="Aurinara Terminology Binding",
                    Name=(
                        f"{binding.terminology_release_id}:{binding.codelist_code}:"
                        f"{binding.term_code or '*'}:{binding.extension_revision_id or ''}"
                    ),
                )
            origin = etree.SubElement(item, _q(def_ns, "Origin"), Type=variable.origin.origin_type)
            origin_text = _origin_text(variable.origin)
            if origin_text:
                _description(origin, origin_text)
            if (dataset.code, variable.name) in grouped_value_levels:
                etree.SubElement(
                    item,
                    _q(def_ns, "ValueListRef"),
                    ValueListOID=f"VL.{dataset.code}.{variable.name}",
                )
        for order, value_level in enumerate(dataset.value_level_metadata, start=1):
            candidate_checks = _condition_checks(
                value_level.condition, dataset.code, known_variables
            )
            if candidate_checks is None:
                continue
            item_attributes = {
                "OID": f"IT.{dataset.code}.{value_level.variable}.VL.{value_level.id.hex}",
                "Name": f"{value_level.variable}.{order}",
                "DataType": "text" if value_level.data_type == "character" else "float",
            }
            if value_level.length is not None:
                item_attributes["Length"] = str(value_level.length)
            item = etree.SubElement(metadata, _q(ODM, "ItemDef"), attrib=item_attributes)
            _description(item, value_level.label)
            if value_level.terminology_binding is not None:
                binding = value_level.terminology_binding
                etree.SubElement(
                    item,
                    _q(ODM, "Alias"),
                    Context="Aurinara Terminology Binding",
                    Name=(
                        f"{binding.terminology_release_id}:{binding.codelist_code}:"
                        f"{binding.term_code or '*'}:{binding.extension_revision_id or ''}"
                    ),
                )
            origin = etree.SubElement(
                item, _q(def_ns, "Origin"), Type=value_level.origin.origin_type
            )
            origin_text = _origin_text(value_level.origin)
            if origin_text:
                _description(origin, origin_text)
    for method in model.methods:
        method_def = etree.SubElement(
            metadata,
            _q(ODM, "MethodDef"),
            OID=method.id,
            Name=method.name,
            Type="Computation",
        )
        _description(method_def, method.description)
    for dataset in model.datasets:
        if dataset.parameters:
            comment = etree.SubElement(
                metadata, _q(def_ns, "CommentDef"), OID=f"COM.PARAM.{dataset.code}"
            )
            _description(
                comment,
                "Parameters: "
                + json.dumps(
                    [item.model_dump(mode="json") for item in dataset.parameters],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        for variable in dataset.variables:
            value_level_payloads = [
                item.model_dump(mode="json")
                for item in dataset.value_level_metadata
                if item.variable == variable.name
            ]
            if value_level_payloads:
                comment = etree.SubElement(
                    metadata,
                    _q(def_ns, "CommentDef"),
                    OID=f"COM.VLM.{dataset.code}.{variable.name}",
                )
                _description(
                    comment,
                    "Value-level metadata: "
                    + json.dumps(
                        value_level_payloads,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
    for leaf in model.leaves:
        element = etree.SubElement(metadata, _q(def_ns, "leaf"), ID=leaf.id)
        element.set(_q(XLINK, "href"), leaf.href)
        etree.SubElement(element, _q(def_ns, "title")).text = leaf.title
    data = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    validate_define_xml(data, version)
    return data


def validate_define_xml(data: bytes, version: DefineXmlVersion) -> None:
    """Validate ADaM Define bytes against repository-pinned schemas without network access."""

    entry = _SCHEMA_ROOT / version / ("define2-0-0.xsd" if version == "2.0" else "define2-1-0.xsd")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        schema = etree.XMLSchema(etree.parse(str(entry), parser))
        document = etree.fromstring(data, parser)
    except (OSError, etree.XMLSyntaxError, etree.XMLSchemaParseError) as error:
        raise _problem(
            "adam_define_xsd_unavailable", "Pinned Define XSD loading failed."
        ) from error
    if not schema.validate(document):
        raise _problem(
            "adam_define_xsd_validation_failed",
            str(schema.error_log) or "Define XSD validation failed.",
        )


def define_schema_fingerprint(version: DefineXmlVersion) -> str:
    """Fingerprint every local schema byte used for one Define version."""

    digest = hashlib.sha256()
    for directory in (
        _SCHEMA_ROOT / version,
        _SCHEMA_ROOT / "cdisc-odm-1.3.2",
        _SCHEMA_ROOT / "core",
    ):
        for path in sorted(directory.glob("*.xsd")):
            digest.update(str(path.relative_to(_SCHEMA_ROOT)).replace("\\", "/").encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _problem(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422,
        code=code,
        title="ADaM Define-XML rendering failed",
        detail=detail,
    )
