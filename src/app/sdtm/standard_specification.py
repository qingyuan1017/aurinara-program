"""Initialize SDTM Specification structures from exact industry metadata."""

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Literal, cast

from app.sdtm.contracts import (
    SdtmDomain,
    SdtmSpecification,
    SdtmStandardDomainOption,
    SdtmVariable,
)
from app.standards.metadata_resolution import ResolvedStandardMetadata


def _objects(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping))


def _required_text(source: Mapping[str, object], field: str, context: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} is missing {field}")
    return value.strip()


def _class_name(source: Mapping[str, object]) -> str:
    links = source.get("_links")
    if isinstance(links, Mapping):
        parent = links.get("parentClass")
        if isinstance(parent, Mapping):
            title = parent.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
    return "Standard"


def _variable(source: Mapping[str, object], domain_code: str) -> SdtmVariable:
    name = _required_text(source, "name", f"standard domain {domain_code} variable")
    datatype = _required_text(source, "simpleDatatype", f"standard variable {domain_code}.{name}")
    if datatype not in {"Char", "Num"}:
        raise ValueError(
            f"standard variable {domain_code}.{name} has unsupported datatype {datatype}"
        )
    core = _required_text(source, "core", f"standard variable {domain_code}.{name}")
    if core not in {"Req", "Exp", "Perm"}:
        raise ValueError(f"standard variable {domain_code}.{name} has unsupported core {core}")
    return SdtmVariable(
        name=name,
        label=_required_text(source, "label", f"standard variable {domain_code}.{name}"),
        data_type="character" if datatype == "Char" else "numeric",
        role=_required_text(source, "role", f"standard variable {domain_code}.{name}"),
        core=cast(Literal["Req", "Exp", "Perm"], core),
        origin="Standard",
    )


def _domain(source: Mapping[str, object]) -> SdtmDomain | None:
    label = _required_text(source, "label", "standard dataset")
    # SUPPQUAL is a parameterized dataset pattern, not one concrete output.
    # Users create the applicable SUPP-- datasets manually for their study.
    if "[domain name]" in label.casefold():
        return None
    code = _required_text(source, "name", "standard dataset")
    variables = tuple(_variable(item, code) for item in _objects(source.get("datasetVariables")))
    if not variables:
        raise ValueError(f"standard domain {code} has no variables")
    identifiers = tuple(item.name for item in variables if item.role == "Identifier")
    keys = identifiers or (variables[0].name,)
    return SdtmDomain(
        code=code,
        label=label,
        domain_class=_class_name(source),
        structure=_required_text(source, "datasetStructure", f"standard domain {code}"),
        keys=keys,
        sort_order=keys,
        expected_output_name=f"{code.lower()}.xpt",
        variables=variables,
    )


def _standard_domains(payload: Mapping[str, object]) -> tuple[SdtmDomain, ...]:
    domains: list[SdtmDomain] = []
    seen: set[str] = set()
    for standard_class in _objects(payload.get("classes")):
        for dataset in _objects(standard_class.get("datasets")):
            domain = _domain(dataset)
            if domain is None:
                continue
            if domain.code in seen:
                raise ValueError(f"standard metadata contains duplicate domain {domain.code}")
            seen.add(domain.code)
            domains.append(domain)
    if not domains:
        raise ValueError("the selected standard metadata contains no concrete SDTM domains")
    return tuple(domains)


def _validate_sdtmig(metadata: ResolvedStandardMetadata) -> tuple[SdtmDomain, ...]:
    if not metadata.product_code.startswith("SDTMIG"):
        raise ValueError("the selected standard must be an SDTM implementation guide")
    return _standard_domains(metadata.payload)


def standard_domain_options(
    metadata: ResolvedStandardMetadata,
) -> tuple[SdtmStandardDomainOption, ...]:
    """Describe concrete domains available from one exact SDTMIG release."""

    return tuple(
        SdtmStandardDomainOption(
            code=domain.code,
            label=domain.label,
            domain_class=domain.domain_class,
            required_variable_count=sum(variable.core == "Req" for variable in domain.variables),
            expected_variable_count=sum(variable.core == "Exp" for variable in domain.variables),
            permissible_variable_count=sum(
                variable.core == "Perm" for variable in domain.variables
            ),
        )
        for domain in _validate_sdtmig(metadata)
    )


def _selected_domains(
    standard_domains: tuple[SdtmDomain, ...],
    domain_codes: Collection[str] | None,
    *,
    core_variables_only: bool,
) -> tuple[SdtmDomain, ...]:
    selected_codes = (
        {item.upper() for item in domain_codes}
        if domain_codes is not None
        else {item.code for item in standard_domains}
    )
    known_codes = {item.code for item in standard_domains}
    unknown_codes = sorted(selected_codes - known_codes)
    if unknown_codes:
        raise ValueError(
            "the selected standard does not contain concrete domain(s): " + ", ".join(unknown_codes)
        )

    selected: list[SdtmDomain] = []
    for domain in standard_domains:
        if domain.code not in selected_codes:
            continue
        variables = tuple(
            variable
            for variable in domain.variables
            if not core_variables_only or variable.core in {"Req", "Exp"}
        )
        if not variables:
            raise ValueError(f"standard domain {domain.code} has no Required or Expected variables")
        names = {item.name for item in variables}
        keys = tuple(item for item in domain.keys if item in names)
        if not keys:
            identifiers = tuple(item.name for item in variables if item.role == "Identifier")
            keys = identifiers or (variables[0].name,)
        sort_order = tuple(item for item in domain.sort_order if item in names) or keys
        selected.append(
            domain.model_copy(
                update={
                    "variables": variables,
                    "keys": keys,
                    "sort_order": sort_order,
                }
            )
        )
    return tuple(selected)


def _merge_variables(
    current: Iterable[SdtmVariable], standard: Iterable[SdtmVariable]
) -> tuple[SdtmVariable, ...]:
    result = list(current)
    known = {item.name for item in result}
    result.extend(item for item in standard if item.name not in known)
    return tuple(result)


def initialize_specification_from_standard(
    metadata: ResolvedStandardMetadata,
    current: SdtmSpecification | None = None,
    *,
    domain_codes: Collection[str] | None = None,
    core_variables_only: bool = False,
) -> SdtmSpecification:
    """Add selected standard domains and variables while preserving authored values."""

    standard_domains = _selected_domains(
        _validate_sdtmig(metadata),
        domain_codes,
        core_variables_only=core_variables_only,
    )
    if current is None:
        return SdtmSpecification(domains=standard_domains)

    standard_by_code = {item.code: item for item in standard_domains}
    merged: list[SdtmDomain] = []
    for domain in current.domains:
        standard = standard_by_code.pop(domain.code, None)
        if standard is None:
            merged.append(domain)
            continue
        merged.append(
            domain.model_copy(
                update={"variables": _merge_variables(domain.variables, standard.variables)}
            )
        )
    merged.extend(domain for domain in standard_domains if domain.code in standard_by_code)
    return SdtmSpecification(domains=tuple(merged))
