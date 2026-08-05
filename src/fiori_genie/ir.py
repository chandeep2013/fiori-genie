"""Intermediate representation for a CAP application.

The LLM never emits CDS source. It emits an instance of `AppModel`, which is
validated here and then rendered deterministically by `render/`. Everything a
generator needs to produce schema, service, annotations, sample data and tests
has to be expressible in this file.
"""

from __future__ import annotations

import keyword
import re
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# Rejected as identifiers because the compiler will either error or silently
# reinterpret them. Not exhaustive; the `cds compile` step is the real gate.
CDS_RESERVED = {
    "action", "annotate", "aspect", "as", "by", "context", "define", "entity",
    "event", "extend", "from", "function", "key", "namespace", "returns",
    "select", "service", "type", "using", "where", "with", "view", "on",
    "mixin", "into", "group", "order", "having", "distinct", "join", "union",
    "excluding", "virtual", "array", "many", "one", "null", "true", "false",
}


class CdsType(str, Enum):
    UUID = "UUID"
    Boolean = "Boolean"
    Integer = "Integer"
    Int16 = "Int16"
    Int64 = "Int64"
    Decimal = "Decimal"
    Double = "Double"
    Date = "Date"
    Time = "Time"
    DateTime = "DateTime"
    Timestamp = "Timestamp"
    String = "String"
    LargeString = "LargeString"


class Cardinality(str, Enum):
    TO_ONE = "to-one"
    TO_MANY = "to-many"


class RelationKind(str, Enum):
    ASSOCIATION = "association"
    COMPOSITION = "composition"


class Floorplan(str, Enum):
    LIST_REPORT = "list-report"
    WORKLIST = "worklist"
    OBJECT_PAGE_ONLY = "object-page-only"


def _check_identifier(value: str, what: str) -> str:
    if not IDENT_RE.match(value):
        raise ValueError(
            f"{what} '{value}' is not a valid CDS identifier "
            "(letters, digits, underscore; must start with a letter)"
        )
    if value.lower() in CDS_RESERVED or keyword.iskeyword(value.lower()):
        raise ValueError(f"{what} '{value}' is a reserved CDS keyword")
    return value


class Field_(BaseModel):
    """A scalar element of an entity."""

    # Titled explicitly: the class name carries a trailing underscore to avoid
    # colliding with pydantic's Field, and that would otherwise surface in the
    # JSON schema the model sees.
    model_config = ConfigDict(populate_by_name=True, title="Field")

    name: str
    type: CdsType
    label: Optional[str] = Field(
        default=None, description="Human-readable @title used by Fiori elements"
    )
    doc: Optional[str] = None

    is_key: bool = Field(default=False, alias="key")
    not_null: bool = Field(default=False, alias="notNull")

    length: Optional[int] = Field(
        default=None, description="String length. Defaults to 255 when omitted."
    )
    precision: Optional[int] = None
    scale: Optional[int] = None

    default: Optional[str] = Field(
        default=None, description="Literal default, rendered verbatim into CDS"
    )
    # Rendered as an inline enum. Keys are technical codes, values are labels.
    enum_values: Optional[Dict[str, str]] = Field(default=None, alias="enum")

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_identifier(v, "Field name")

    @field_validator("enum_values", mode="before")
    @classmethod
    def _coerce_enum(cls, v):
        """Accept Gemini/OpenAI quirks: empty enum, or a plain list of codes."""
        if v is None or v == {} or v == []:
            return None
        if isinstance(v, list):
            coerced = {}
            for item in v:
                if isinstance(item, dict):
                    code = str(item.get("code") or item.get("value") or item.get("name") or "")
                    label = str(item.get("label") or item.get("title") or code)
                else:
                    code = str(item)
                    label = code
                if code:
                    coerced[code] = label
            return coerced or None
        return v

    @model_validator(mode="after")
    def _check_facets(self) -> "Field_":
        if self.length is not None:
            if self.type is not CdsType.String:
                raise ValueError(
                    f"Field '{self.name}': length only applies to String, not {self.type.value}"
                )
            if self.length < 1:
                raise ValueError(f"Field '{self.name}': length must be >= 1")

        if self.type is CdsType.Decimal:
            if self.precision is None or self.scale is None:
                raise ValueError(
                    f"Field '{self.name}': Decimal requires both precision and scale"
                )
            if self.scale > self.precision:
                raise ValueError(
                    f"Field '{self.name}': scale ({self.scale}) cannot exceed "
                    f"precision ({self.precision})"
                )
        elif self.precision is not None or self.scale is not None:
            raise ValueError(
                f"Field '{self.name}': precision/scale only apply to Decimal"
            )

        if self.enum_values is not None:
            if self.type not in (CdsType.String, CdsType.Integer):
                raise ValueError(
                    f"Field '{self.name}': enum only supported on String or Integer"
                )
            if not self.enum_values:
                raise ValueError(f"Field '{self.name}': enum cannot be empty")
            # Codes become CDS enum symbols, so they must be identifiers.
            for code in self.enum_values:
                if not IDENT_RE.match(code):
                    raise ValueError(
                        f"Field '{self.name}': enum code '{code}' must be a valid "
                        "identifier (e.g. 'IN_REVIEW', not 'in review' or '01')"
                    )

        return self


class Relation(BaseModel):
    """An association or composition to another entity in the model.

    Only managed relations are produced. A to-one renders as a managed
    association using the target's key; a to-many requires `backlink`, the
    field on the target that points back here.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    target: str = Field(description="Name of another entity in this model")
    cardinality: Cardinality = Cardinality.TO_ONE
    kind: RelationKind = RelationKind.ASSOCIATION
    label: Optional[str] = None
    backlink: Optional[str] = Field(
        default=None,
        description="Required for to-many: the to-one relation on the target "
        "that points back to this entity.",
    )
    not_null: bool = Field(default=False, alias="notNull")

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_identifier(v, "Relation name")

    @field_validator("target")
    @classmethod
    def _valid_target(cls, v: str) -> str:
        return _check_identifier(v, "Relation target")

    @model_validator(mode="after")
    def _check_backlink(self) -> "Relation":
        if self.cardinality is Cardinality.TO_MANY and not self.backlink:
            raise ValueError(
                f"Relation '{self.name}' is to-many and needs a 'backlink' naming "
                f"the field on '{self.target}' that points back"
            )
        if self.cardinality is Cardinality.TO_ONE and self.backlink:
            raise ValueError(
                f"Relation '{self.name}' is to-one and must not set 'backlink'"
            )
        return self


class HeaderInfo(BaseModel):
    """Drives @UI.HeaderInfo on the object page."""

    type_name: str = Field(alias="typeName")
    type_name_plural: str = Field(alias="typeNamePlural")
    title_field: str = Field(alias="titleField")
    description_field: Optional[str] = Field(default=None, alias="descriptionField")

    model_config = ConfigDict(populate_by_name=True)


class FieldGroup(BaseModel):
    """A titled group of fields, rendered as a section on the object page."""

    id: str
    label: str
    fields: List[str]

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        return _check_identifier(v, "FieldGroup id")


class UiSpec(BaseModel):
    """Everything needed to emit Fiori elements annotations for one entity."""

    model_config = ConfigDict(populate_by_name=True)

    floorplan: Floorplan = Floorplan.LIST_REPORT
    header_info: Optional[HeaderInfo] = Field(default=None, alias="headerInfo")
    line_item: List[str] = Field(
        default_factory=list,
        alias="lineItem",
        description="Columns of the list report table, in order",
    )
    selection_fields: List[str] = Field(
        default_factory=list,
        alias="selectionFields",
        description="Fields offered in the filter bar",
    )
    field_groups: List[FieldGroup] = Field(default_factory=list, alias="fieldGroups")


class Entity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    label: Optional[str] = None
    doc: Optional[str] = None

    use_cuid: bool = Field(
        default=True,
        alias="useCuid",
        description="Include the cuid aspect, giving a generated UUID key. When "
        "false the model must declare at least one key field.",
    )
    use_managed: bool = Field(
        default=True,
        alias="useManaged",
        description="Include the managed aspect (createdAt/createdBy/modifiedAt/modifiedBy)",
    )

    fields: List[Field_] = Field(default_factory=list)
    relations: List[Relation] = Field(default_factory=list)
    ui: Optional[UiSpec] = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_identifier(v, "Entity name")

    @model_validator(mode="after")
    def _check_entity(self) -> "Entity":
        member_names = [f.name for f in self.fields] + [r.name for r in self.relations]
        dupes = {n for n in member_names if member_names.count(n) > 1}
        if dupes:
            raise ValueError(
                f"Entity '{self.name}' has duplicate members: {sorted(dupes)}"
            )

        if not self.use_cuid and not any(f.is_key for f in self.fields):
            raise ValueError(
                f"Entity '{self.name}' has useCuid=false but declares no key field"
            )
        if self.use_cuid and any(f.is_key for f in self.fields):
            raise ValueError(
                f"Entity '{self.name}' uses the cuid aspect (which supplies the key) "
                "but also declares an explicit key field; set useCuid=false or drop the key"
            )
        return self

    def member_names(self) -> List[str]:
        return [f.name for f in self.fields] + [r.name for r in self.relations]


class ExposedEntity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    entity: str
    as_name: Optional[str] = Field(
        default=None, alias="as", description="Projection name; defaults to the entity name"
    )
    draft_enabled: bool = Field(default=True, alias="draftEnabled")
    readonly: bool = False

    @model_validator(mode="after")
    def _check_flags(self) -> "ExposedEntity":
        if self.readonly and self.draft_enabled:
            raise ValueError(
                f"'{self.entity}' cannot be both readonly and draft-enabled"
            )
        return self

    @property
    def exposed_name(self) -> str:
        return self.as_name or self.entity


class Service(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    path: Optional[str] = None
    entities: List[ExposedEntity] = Field(default_factory=list)
    requires: Optional[str] = Field(
        default=None,
        description="Restrict the whole service, e.g. 'authenticated-user' or a role",
    )

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_identifier(v, "Service name")


class FioriApp(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(description="App id, e.g. 'purchaserequisition'")
    title: str
    description: Optional[str] = None
    service: str
    main_entity: str = Field(alias="mainEntity")

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9]*$", v):
            raise ValueError(
                f"App id '{v}' must be lowercase alphanumeric, starting with a letter"
            )
        return v


class AppModel(BaseModel):
    """Root of the intermediate representation."""

    model_config = ConfigDict(populate_by_name=True)

    namespace: str = Field(description="Dot-separated, e.g. 'com.acme.procurement'")
    project_name: str = Field(alias="projectName")
    description: Optional[str] = None

    entities: List[Entity]
    services: List[Service]
    apps: List[FioriApp] = Field(default_factory=list)

    sample_data: Dict[str, List[Dict[str, object]]] = Field(
        default_factory=dict,
        alias="sampleData",
        description="Entity name -> list of row dicts, used to emit db/data CSVs",
    )

    @field_validator("namespace")
    @classmethod
    def _valid_namespace(cls, v: str) -> str:
        for part in v.split("."):
            _check_identifier(part, "Namespace segment")
        return v

    @field_validator("project_name")
    @classmethod
    def _valid_project(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9-]*$", v):
            raise ValueError(
                f"Project name '{v}' must be lowercase alphanumeric with hyphens"
            )
        return v

    def entity(self, name: str) -> Optional[Entity]:
        return next((e for e in self.entities if e.name == name), None)
