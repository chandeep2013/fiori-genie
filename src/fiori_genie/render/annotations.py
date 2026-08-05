"""Builds Fiori elements UI annotations from the IR.

Written as string assembly rather than a template because annotation records
are comma-separated and deeply nested; joining lists of rendered blocks makes
trailing-comma errors structurally impossible.
"""

from __future__ import annotations

from typing import List, Optional

from ..ir import AppModel, Cardinality, Entity, FioriApp, RelationKind, Service


def cds_str(value: str) -> str:
    """Escape a Python string for a single-quoted CDS literal."""
    return value.replace("'", "''")


def indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.split("\n"))


def ui_value(model: AppModel, entity: Entity, member: str) -> str:
    """Resolve a member name to the expression Fiori elements should bind to.

    A to-one association renders as a path to the target's title field when one
    is known, so tables show a readable name instead of a raw UUID foreign key.
    """
    rel = next((r for r in entity.relations if r.name == member), None)
    if rel is None:
        return member

    if rel.cardinality is Cardinality.TO_MANY:
        # Only meaningful as a facet target, never as a DataField value.
        return member

    target = model.entity(rel.target)
    if target is not None and target.ui is not None and target.ui.header_info is not None:
        return f"{rel.name}.{target.ui.header_info.title_field}"
    if target is not None:
        first_string = next(
            (f.name for f in target.fields if f.type.value in ("String", "LargeString")),
            None,
        )
        if first_string:
            return f"{rel.name}.{first_string}"
    return f"{rel.name}_ID"


def _header_info(model: AppModel, entity: Entity) -> Optional[str]:
    info = entity.ui.header_info if entity.ui else None
    if info is None:
        return None

    lines = [
        "HeaderInfo : {",
        "  $Type          : 'UI.HeaderInfoType',",
        f"  TypeName       : '{cds_str(info.type_name)}',",
        f"  TypeNamePlural : '{cds_str(info.type_name_plural)}',",
    ]
    title = ui_value(model, entity, info.title_field)
    if info.description_field:
        desc = ui_value(model, entity, info.description_field)
        lines.append(f"  Title          : {{ $Type: 'UI.DataField', Value: {title} }},")
        lines.append(f"  Description    : {{ $Type: 'UI.DataField', Value: {desc} }}")
    else:
        lines.append(f"  Title          : {{ $Type: 'UI.DataField', Value: {title} }}")
    lines.append("}")
    return "\n".join(lines)


def _selection_fields(model: AppModel, entity: Entity) -> Optional[str]:
    names = entity.ui.selection_fields if entity.ui else []
    if not names:
        return None
    items = [f"  {ui_value(model, entity, n)}" for n in names]
    return "SelectionFields : [\n" + ",\n".join(items) + "\n]"


def _line_item(model: AppModel, entity: Entity) -> Optional[str]:
    names = entity.ui.line_item if entity.ui else []
    if not names:
        return None
    items = [
        f"  {{ $Type: 'UI.DataField', Value: {ui_value(model, entity, n)} }}"
        for n in names
    ]
    return "LineItem : [\n" + ",\n".join(items) + "\n]"


def _field_groups(model: AppModel, entity: Entity) -> List[str]:
    blocks = []
    for group in entity.ui.field_groups if entity.ui else []:
        items = [
            f"    {{ $Type: 'UI.DataField', Value: {ui_value(model, entity, n)} }}"
            for n in group.fields
        ]
        blocks.append(
            f"FieldGroup #{group.id} : {{\n"
            "  $Type : 'UI.FieldGroupType',\n"
            "  Data  : [\n" + ",\n".join(items) + "\n  ]\n}"
        )
    return blocks


def _facets(model: AppModel, entity: Entity) -> Optional[str]:
    """One reference facet per field group, then one table facet per child list."""
    entries: List[str] = []

    for group in entity.ui.field_groups if entity.ui else []:
        entries.append(
            "  {\n"
            "    $Type  : 'UI.ReferenceFacet',\n"
            f"    ID     : '{group.id}',\n"
            f"    Label  : '{cds_str(group.label)}',\n"
            f"    Target : '@UI.FieldGroup#{group.id}'\n"
            "  }"
        )

    for rel in entity.relations:
        if rel.cardinality is not Cardinality.TO_MANY:
            continue
        target = model.entity(rel.target)
        if target is None or target.ui is None or not target.ui.line_item:
            continue  # nothing to render a table from
        label = rel.label
        if not label and target.ui.header_info is not None:
            label = target.ui.header_info.type_name_plural
        if not label:
            label = rel.name
        entries.append(
            "  {\n"
            "    $Type  : 'UI.ReferenceFacet',\n"
            f"    ID     : '{rel.name}Facet',\n"
            f"    Label  : '{cds_str(label)}',\n"
            f"    Target : '{rel.name}/@UI.LineItem'\n"
            "  }"
        )

    if not entries:
        return None
    return "Facets : [\n" + ",\n".join(entries) + "\n]"


def annotate_entity(model: AppModel, entity: Entity, exposed_name: str) -> Optional[str]:
    """Render one `annotate ... with @( UI: { ... } );` statement."""
    if entity.ui is None:
        return None

    blocks: List[str] = []
    for block in (
        _header_info(model, entity),
        _selection_fields(model, entity),
        _line_item(model, entity),
        _facets(model, entity),
    ):
        if block:
            blocks.append(block)
    blocks.extend(_field_groups(model, entity))

    if not blocks:
        return None

    body = ",\n".join(blocks)
    return (
        f"annotate service.{exposed_name} with @(\n"
        "  UI : {\n" + indent(body, 4) + "\n  }\n);"
    )


def _entities_for_app(model: AppModel, app: FioriApp, service: Service) -> List[tuple]:
    """Main entity first, then composition children exposed by the same service."""
    by_exposed = {e.exposed_name: e.entity for e in service.entities}
    ordered = [app.main_entity]

    main_entity = model.entity(by_exposed.get(app.main_entity, ""))
    if main_entity is not None:
        for rel in main_entity.relations:
            if rel.kind is not RelationKind.COMPOSITION:
                continue
            for exposed_name, entity_name in by_exposed.items():
                if entity_name == rel.target and exposed_name not in ordered:
                    ordered.append(exposed_name)

    result = []
    for exposed_name in ordered:
        entity = model.entity(by_exposed.get(exposed_name, ""))
        if entity is not None:
            result.append((exposed_name, entity))
    return result


def render_annotations(model: AppModel, app: FioriApp) -> str:
    service = next((s for s in model.services if s.name == app.service), None)
    if service is None:
        raise ValueError(f"App '{app.id}' references unknown service '{app.service}'")

    statements = []
    for exposed_name, entity in _entities_for_app(model, app, service):
        statement = annotate_entity(model, entity, exposed_name)
        if statement:
            statements.append(statement)

    header = f"using {{ {service.name} as service }} from '../../srv/service';\n"
    return header + "\n" + "\n\n".join(statements) + "\n"
