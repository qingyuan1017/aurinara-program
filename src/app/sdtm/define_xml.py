"""Deterministic Define-XML 2.0/2.1 rendering and pinned-XSD validation."""

import hashlib
from pathlib import Path
from typing import Literal

from lxml import etree

from app.common.problems import ProblemException
from app.sdtm.contracts import SdtmDefineModel

DefineXmlVersion = Literal["2.0", "2.1"]
ODM = "http://www.cdisc.org/ns/odm/v1.3"
XLINK = "http://www.w3.org/1999/xlink"
XML = "http://www.w3.org/XML/1998/namespace"
GENERATOR_VERSION = "1.0.0"
_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas" / "cdisc" / "define-xml"


def _q(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _description(parent: etree._Element, value: str) -> None:
    description = etree.SubElement(parent, _q(ODM, "Description"))
    translated = etree.SubElement(description, _q(ODM, "TranslatedText"))
    translated.set(_q(XML, "lang"), "en")
    translated.text = value


def render_define_xml(model: SdtmDefineModel, version: DefineXmlVersion) -> bytes:
    """Render one version-neutral model deterministically and prove XSD validity."""

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
    for name, text in (
        ("StudyName", model.name),
        ("StudyDescription", model.description or model.name),
        ("ProtocolName", model.study_oid),
    ):
        etree.SubElement(global_variables, _q(ODM, name)).text = text
    metadata_attributes = {
        "OID": model.metadata_version_oid,
        "Name": model.name,
        _q(def_ns, "DefineVersion"): f"{version}.0",
    }
    if model.description is not None:
        metadata_attributes["Description"] = model.description
    if version == "2.0":
        metadata_attributes[_q(def_ns, "StandardName")] = model.standard_name
        metadata_attributes[_q(def_ns, "StandardVersion")] = model.standard_version
    metadata = etree.SubElement(study, _q(ODM, "MetaDataVersion"), attrib=metadata_attributes)
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
    for document in model.document_references:
        supplemental = etree.SubElement(metadata, _q(def_ns, "SupplementalDoc"))
        etree.SubElement(supplemental, _q(def_ns, "DocumentRef"), leafID=document.id)
    for dataset in model.datasets:
        attributes = {
            "OID": dataset.oid,
            "Name": dataset.name,
            "Repeating": "Yes" if dataset.repeating else "No",
            "IsReferenceData": "Yes" if dataset.reference_data else "No",
            "SASDatasetName": dataset.name,
            "Domain": dataset.name,
            "Purpose": dataset.purpose,
            _q(def_ns, "Structure"): dataset.structure,
        }
        if dataset.leaf_id is not None:
            attributes[_q(def_ns, "ArchiveLocationID")] = dataset.leaf_id
        if version == "2.0":
            attributes[_q(def_ns, "Class")] = dataset.dataset_class
        else:
            attributes[_q(def_ns, "StandardOID")] = "STD.1"
        group = etree.SubElement(metadata, _q(ODM, "ItemGroupDef"), attrib=attributes)
        _description(group, dataset.label)
        for order, item in enumerate(dataset.items, start=1):
            item_ref_attributes = {
                "ItemOID": item.oid,
                "OrderNumber": str(order),
                "Mandatory": "Yes" if item.mandatory else "No",
            }
            if item.role is not None:
                item_ref_attributes["Role"] = item.role
            if item.method_id is not None:
                item_ref_attributes["MethodOID"] = item.method_id
            etree.SubElement(group, _q(ODM, "ItemRef"), attrib=item_ref_attributes)
        if version == "2.1":
            etree.SubElement(group, _q(def_ns, "Class"), Name=dataset.dataset_class.upper())
    for dataset in model.datasets:
        for item in dataset.items:
            attributes = {
                "OID": item.oid,
                "Name": item.name,
                "DataType": item.data_type,
            }
            if item.length is not None:
                attributes["Length"] = str(item.length)
            if item.comment_id is not None:
                attributes[_q(def_ns, "CommentOID")] = item.comment_id
            item_def = etree.SubElement(metadata, _q(ODM, "ItemDef"), attrib=attributes)
            _description(item_def, item.label)
            if item.codelist_id is not None:
                etree.SubElement(item_def, _q(ODM, "CodeListRef"), CodeListOID=item.codelist_id)
            origin = etree.SubElement(item_def, _q(def_ns, "Origin"), Type=item.origin.origin_type)
            if item.origin.description:
                _description(origin, item.origin.description)
            for reference_id in item.origin.document_reference_ids:
                etree.SubElement(origin, _q(def_ns, "DocumentRef"), leafID=reference_id)
    for codelist in model.codelists:
        if not codelist.items:
            raise _render_problem(
                "define_codelist_empty", f"CodeList '{codelist.id}' has no authored items."
            )
        code_list = etree.SubElement(
            metadata,
            _q(ODM, "CodeList"),
            OID=codelist.id,
            Name=codelist.name,
            DataType=codelist.data_type,
        )
        for code_item_contract in codelist.items:
            attributes = {"CodedValue": code_item_contract.coded_value}
            if code_item_contract.rank is not None:
                attributes["Rank"] = str(code_item_contract.rank)
            code_item = etree.SubElement(code_list, _q(ODM, "CodeListItem"), attrib=attributes)
            decode = etree.SubElement(code_item, _q(ODM, "Decode"))
            etree.SubElement(decode, _q(ODM, "TranslatedText")).text = code_item_contract.decode
    for method in model.methods:
        method_def = etree.SubElement(
            metadata,
            _q(ODM, "MethodDef"),
            OID=method.id,
            Name=method.name,
            Type="Computation",
        )
        _description(method_def, method.description)
    for comment in model.comments:
        comment_def = etree.SubElement(metadata, _q(def_ns, "CommentDef"), OID=comment.id)
        _description(comment_def, comment.description)
    leaf_ids = {leaf.id for leaf in model.leaves}
    document_ids = {document.id for document in model.document_references}
    if leaf_ids & document_ids:
        raise _render_problem(
            "define_leaf_id_duplicate", "Dataset and document leaf IDs must be unique."
        )
    for leaf_id, title, href in (
        *[(leaf.id, leaf.title, leaf.href) for leaf in model.leaves],
        *[(item.id, item.title, item.href) for item in model.document_references],
    ):
        leaf = etree.SubElement(metadata, _q(def_ns, "leaf"), ID=leaf_id)
        leaf.set(_q(XLINK, "href"), href)
        etree.SubElement(leaf, _q(def_ns, "title")).text = title
    data = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    validate_define_xml(data, version)
    return data


def validate_define_xml(data: bytes, version: DefineXmlVersion) -> None:
    """Validate bytes with the repository-pinned XSD entry point and no network access."""

    entry = _SCHEMA_ROOT / version / ("define2-0-0.xsd" if version == "2.0" else "define2-1-0.xsd")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        schema = etree.XMLSchema(etree.parse(str(entry), parser))
        document = etree.fromstring(data, parser)
    except (OSError, etree.XMLSyntaxError, etree.XMLSchemaParseError) as error:
        raise _render_problem(
            "define_xsd_unavailable", "Pinned Define XSD loading failed."
        ) from error
    if not schema.validate(document):
        detail = str(schema.error_log) or "Define XSD validation failed."
        raise _render_problem("define_xsd_validation_failed", detail)


def define_schema_fingerprint(version: DefineXmlVersion) -> str:
    """Fingerprint every local schema byte that participates in validation."""

    digest = hashlib.sha256()
    directories = (
        _SCHEMA_ROOT / version,
        _SCHEMA_ROOT / "cdisc-odm-1.3.2",
        _SCHEMA_ROOT / "core",
    )
    for directory in directories:
        for path in sorted(directory.glob("*.xsd")):
            digest.update(str(path.relative_to(_SCHEMA_ROOT)).replace("\\", "/").encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _render_problem(code: str, detail: str) -> ProblemException:
    return ProblemException(
        status_code=422,
        code=code,
        title="Define-XML rendering failed",
        detail=detail,
    )
