"""Strict manually authored TLF contracts and exact ADaM bindings."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TlfColumn(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    label: str = Field(min_length=1, max_length=500)
    order: int = Field(ge=1)


class TlfRow(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    parent_id: str | None = None
    label: str = Field(min_length=1, max_length=500)
    order: int = Field(ge=1)
    leaf: bool


class TlfShell(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    output_code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,31}$")
    output_type: Literal["table", "listing", "figure"]
    title: str = Field(min_length=1, max_length=500)
    subtitle: str | None = Field(default=None, max_length=500)
    columns: tuple[TlfColumn, ...] = Field(min_length=1)
    rows: tuple[TlfRow, ...] = Field(min_length=1)
    footnotes: tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...] = ()
    orientation: Literal["portrait", "landscape"] = "portrait"

    @model_validator(mode="after")
    def valid_hierarchy(self) -> "TlfShell":
        column_ids = [item.id for item in self.columns]
        row_ids = [item.id for item in self.rows]
        if len(column_ids) != len(set(column_ids)) or len(row_ids) != len(set(row_ids)):
            raise ValueError("shell column and row IDs must be unique")
        if len({item.order for item in self.columns}) != len(self.columns):
            raise ValueError("shell column order values must be unique")
        known = set(row_ids)
        parents = {item.id: item.parent_id for item in self.rows}
        for row in self.rows:
            if row.parent_id is not None and row.parent_id not in known:
                raise ValueError("shell row parents must resolve")
            if row.parent_id == row.id:
                raise ValueError("shell rows cannot parent themselves")
            current = row.parent_id
            visited = {row.id}
            while current is not None:
                if current in visited:
                    raise ValueError("shell row hierarchy must be acyclic")
                visited.add(current)
                current = parents[current]
        parents_with_children = {item.parent_id for item in self.rows if item.parent_id is not None}
        if any(item.leaf == (item.id in parents_with_children) for item in self.rows):
            raise ValueError("leaf flags must match the shell hierarchy")
        return self


class TlfAdamDatasetBinding(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    adam_id: UUID
    adam_revision: int = Field(ge=1)
    dataset_code: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")
    artifact_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_run_id: UUID
    dependency_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class TlfNamedBinding(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    kind: Literal["population", "parameter", "statistic"]
    dataset_binding_id: str
    variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")
    value: str


class TlfBindings(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    datasets: tuple[TlfAdamDatasetBinding, ...] = Field(min_length=1)
    named: tuple[TlfNamedBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_bindings(self) -> "TlfBindings":
        dataset_ids = [item.id for item in self.datasets]
        named_ids = [item.id for item in self.named]
        artifact_ids = [item.artifact_id for item in self.datasets]
        if len(dataset_ids) != len(set(dataset_ids)) or len(named_ids) != len(set(named_ids)):
            raise ValueError("TLF binding IDs must be unique")
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("ADaM input artifacts must be unique")
        known = set(dataset_ids)
        if any(item.dataset_binding_id not in known for item in self.named):
            raise ValueError("named bindings must reference exact dataset bindings")
        return self


class TlfAssumption(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    text: str = Field(min_length=1, max_length=4000)


class TlfAssumptions(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    items: tuple[TlfAssumption, ...]

    @model_validator(mode="after")
    def unique_ids(self) -> "TlfAssumptions":
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("assumption IDs must be unique")
        return self


class ArsAnalysis(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    leaf_row_id: str
    dataset_binding_id: str
    population_binding_id: str
    parameter_binding_id: str | None = None
    statistic_binding_id: str
    order: int = Field(ge=1)


class TlfArs(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    analyses: tuple[ArsAnalysis, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_analyses(self) -> "TlfArs":
        identifiers = [item.id for item in self.analyses]
        orders = [item.order for item in self.analyses]
        leaves = [item.leaf_row_id for item in self.analyses]
        if len(identifiers) != len(set(identifiers)) or len(orders) != len(set(orders)):
            raise ValueError("ARS analysis IDs and order values must be unique")
        if len(leaves) != len(set(leaves)):
            raise ValueError("every leaf shell row must map to one ARS analysis")
        return self


class TlfAnalysisStep(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    analysis_id: str
    method: Literal["frequency", "descriptive_statistics"]
    variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")
    group_by: tuple[str, ...] = ()
    order: int = Field(ge=1)
    tolerance: float | None = Field(default=None, ge=0)


class TlfProgramPlan(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    shell_revision: int = Field(ge=1)
    bindings_revision: int = Field(ge=1)
    assumptions_revision: int = Field(ge=1)
    ars_revision: int = Field(ge=1)
    output_filename: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,62}\.csv$")
    steps: tuple[TlfAnalysisStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_steps(self) -> "TlfProgramPlan":
        identifiers = [item.id for item in self.steps]
        analyses = [item.analysis_id for item in self.steps]
        orders = [item.order for item in self.steps]
        if len(identifiers) != len(set(identifiers)) or len(orders) != len(set(orders)):
            raise ValueError("ProgramPlan step IDs and order values must be unique")
        if len(analyses) != len(set(analyses)):
            raise ValueError("every ARS analysis must map to one ProgramPlan step")
        return self
