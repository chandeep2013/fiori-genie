"""Helpers that turn IR nodes into CDS source fragments.

Exposed to Jinja as globals/filters. Kept separate from the templates so the
grammar decisions live in testable Python rather than in whitespace-sensitive
template markup.
"""

from __future__ import annotations

import re
from typing import Optional

from ..ir import Cardinality, CdsType, Entity, Field_, Relation, RelationKind, Service


def cds_str(value: str) -> str:
    return value.replace("'", "''")


def type_expr(field: Field_) -> str:
    if field.type is CdsType.String and field.length is not None:
        return f"String({field.length})"
    if field.type is CdsType.Decimal:
        return f"Decimal({field.precision}, {field.scale})"
    return field.type.value


def default_expr(field: Field_) -> Optional[str]:
    """Turn an IR default into a CDS constant expression.

    Models often emit bare codes like `DRAFT`. CDS needs `'DRAFT'` or `#DRAFT`.
    """
    if field.default is None:
        return None
    value = str(field.default).strip()
    if not value:
        return None

    if value.startswith("#"):
        return value
    if value.startswith("'") and value.endswith("'") and len(value) >= 2:
        return value
    if value in {"true", "false", "null"}:
        return value
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return value

    # JSON-style double quotes: "DRAFT"
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        return f"'{cds_str(value[1:-1])}'"

    # Bare enum symbol — prefer the #CODE form CAP documents for enums.
    if field.enum_values and value in field.enum_values:
        return f"#{value}"

    # Case-insensitive match on enum codes (Gemini sometimes sends Draft).
    if field.enum_values:
        for code in field.enum_values:
            if code.lower() == value.lower():
                return f"#{code}"

    if field.type is CdsType.String:
        return f"'{cds_str(value)}'"

    return value


def field_decl(field: Field_, indent: int = 2) -> str:
    """Render one element. Clause order verified against @sap/cds-compiler.

    `indent` is the column the caller has already placed the first line at; the
    enum block needs it to line its continuation lines up underneath.
    """
    head = "key " if field.is_key else ""
    parts = [f"{head}{field.name} : {type_expr(field)}"]

    if field.enum_values:
        width = max(len(code) for code in field.enum_values)
        symbols = "".join(
            f"\n{' ' * (indent + 2)}{code.ljust(width)} = '{cds_str(code)}';"
            for code in field.enum_values
        )
        parts.append(f"enum {{{symbols}\n{' ' * indent}}}")

    default = default_expr(field)
    if default is not None:
        parts.append(f"default {default}")
    if field.not_null:
        parts.append("not null")

    return " ".join(parts) + ";"


def relation_decl(rel: Relation) -> str:
    if rel.cardinality is Cardinality.TO_MANY:
        keyword = (
            "Composition of many"
            if rel.kind is RelationKind.COMPOSITION
            else "Association to many"
        )
        decl = f"{rel.name} : {keyword} {rel.target} on {rel.name}.{rel.backlink} = $self"
    else:
        keyword = (
            "Composition of"
            if rel.kind is RelationKind.COMPOSITION
            else "Association to"
        )
        decl = f"{rel.name} : {keyword} {rel.target}"
        if rel.not_null:
            decl += " not null"

    return decl + ";"


def aspects(entity: Entity) -> str:
    names = []
    if entity.use_cuid:
        names.append("cuid")
    if entity.use_managed:
        names.append("managed")
    return " : " + ", ".join(names) if names else ""


def service_path(service: Service) -> str:
    """The URL segment CAP will serve this service under.

    CAP derives this implicitly, but the generator always emits it explicitly so
    the UI5 manifest and the service definition can never drift apart.
    """
    if service.path:
        return service.path.strip("/")

    name = re.sub(r"Service$", "", service.name) or service.name
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    return kebab


def service_url(service: Service) -> str:
    """The full URL prefix the service is reachable at."""
    return f"/odata/v4/{service_path(service)}"


def service_options(service: Service) -> str:
    # The path is deliberately emitted without a leading slash. A leading slash
    # makes it absolute, which drops the /odata/v4 prefix and silently breaks
    # every generated manifest and test URL.
    options = [f"path: '{service_path(service)}'"]
    if service.requires:
        options.append(f"requires: '{cds_str(service.requires)}'")
    return " @(" + ", ".join(options) + ")"


def register(env) -> None:
    env.filters["cds_str"] = cds_str
    env.globals.update(
        type_expr=type_expr,
        field_decl=field_decl,
        default_expr=default_expr,
        relation_decl=relation_decl,
        aspects=aspects,
        service_options=service_options,
        service_path=service_path,
        service_url=service_url,
    )
