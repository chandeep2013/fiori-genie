"""Whole-model semantic validation.

Pydantic validates each object in isolation. This module checks the things that
only make sense across the graph: do relation targets exist, does a backlink
actually point back, do UI annotations reference real fields.

Catching these here rather than at `cds compile` matters because the messages
are written to be fed back to the model as repair instructions, so they name
the offending path and say what a correct value looks like.
"""

from __future__ import annotations

from typing import List

from .ir import AppModel, Cardinality, Entity, RelationKind


def _dupes(names: List[str]) -> List[str]:
    return sorted({n for n in names if names.count(n) > 1})


def _known_members(entity: Entity) -> List[str]:
    """Members addressable in annotations, including aspect-supplied ones."""
    members = entity.member_names()
    if entity.use_cuid:
        members.append("ID")
    if entity.use_managed:
        members += ["createdAt", "createdBy", "modifiedAt", "modifiedBy"]
    return members


def validate_model(model: AppModel) -> List[str]:
    """Return a list of human-readable problems. Empty means the model is sound."""
    errors: List[str] = []
    entity_names = [e.name for e in model.entities]

    for dupe in _dupes(entity_names):
        errors.append(f"Duplicate entity name '{dupe}'")
    for dupe in _dupes([s.name for s in model.services]):
        errors.append(f"Duplicate service name '{dupe}'")
    for dupe in _dupes([a.id for a in model.apps]):
        errors.append(f"Duplicate app id '{dupe}'")

    if not model.entities:
        errors.append("Model has no entities")
    if not model.services:
        errors.append("Model has no services; at least one is required")

    known = set(entity_names)

    for entity in model.entities:
        _validate_relations(model, entity, known, errors)
        _validate_ui(entity, errors)

    _validate_services(model, known, errors)
    _validate_apps(model, errors)
    _validate_sample_data(model, errors)

    return errors


def _validate_relations(
    model: AppModel, entity: Entity, known: set, errors: List[str]
) -> None:
    for rel in entity.relations:
        if rel.target not in known:
            errors.append(
                f"{entity.name}.{rel.name}: target entity '{rel.target}' does not "
                f"exist. Known entities: {sorted(known)}"
            )
            continue

        if rel.cardinality is not Cardinality.TO_MANY:
            continue

        target = model.entity(rel.target)
        assert target is not None  # guarded above
        back = next((r for r in target.relations if r.name == rel.backlink), None)
        if back is None:
            errors.append(
                f"{entity.name}.{rel.name}: backlink '{rel.backlink}' is not a "
                f"relation on '{rel.target}'. Add a to-one relation named "
                f"'{rel.backlink}' on '{rel.target}' targeting '{entity.name}'."
            )
        elif back.target != entity.name:
            errors.append(
                f"{entity.name}.{rel.name}: backlink '{rel.target}.{rel.backlink}' "
                f"targets '{back.target}', expected '{entity.name}'"
            )
        elif back.cardinality is not Cardinality.TO_ONE:
            errors.append(
                f"{entity.name}.{rel.name}: backlink '{rel.target}.{rel.backlink}' "
                "must be to-one"
            )


def _validate_ui(entity: Entity, errors: List[str]) -> None:
    if entity.ui is None:
        return

    members = set(_known_members(entity))

    def check(field_name: str, where: str) -> None:
        if field_name not in members:
            errors.append(
                f"{entity.name}.ui.{where}: '{field_name}' is not a member of "
                f"'{entity.name}'. Available: {sorted(members)}"
            )

    for name in entity.ui.line_item:
        check(name, "lineItem")
    for name in entity.ui.selection_fields:
        check(name, "selectionFields")

    if entity.ui.header_info is not None:
        check(entity.ui.header_info.title_field, "headerInfo.titleField")
        if entity.ui.header_info.description_field:
            check(entity.ui.header_info.description_field, "headerInfo.descriptionField")

    group_ids = [g.id for g in entity.ui.field_groups]
    for dupe in _dupes(group_ids):
        errors.append(f"{entity.name}.ui: duplicate fieldGroup id '{dupe}'")

    for group in entity.ui.field_groups:
        if not group.fields:
            errors.append(
                f"{entity.name}.ui.fieldGroups[{group.id}]: group has no fields"
            )
        for name in group.fields:
            check(name, f"fieldGroups[{group.id}]")


def _composition_children(model: AppModel) -> dict:
    """Entity name -> name of the parent that composes it."""
    children = {}
    for entity in model.entities:
        for rel in entity.relations:
            if rel.kind is RelationKind.COMPOSITION:
                children[rel.target] = entity.name
    return children


def _validate_services(model: AppModel, known: set, errors: List[str]) -> None:
    children = _composition_children(model)

    for service in model.services:
        if not service.entities:
            errors.append(f"Service '{service.name}' exposes no entities")

        for dupe in _dupes([e.exposed_name for e in service.entities]):
            errors.append(
                f"Service '{service.name}' exposes two entities as '{dupe}'"
            )

        for exposed in service.entities:
            if exposed.entity not in known:
                errors.append(
                    f"Service '{service.name}' exposes unknown entity "
                    f"'{exposed.entity}'. Known entities: {sorted(known)}"
                )
                continue

            # CAP draft-enables composition children along with their root.
            # Annotating the child as well is an error at compile time.
            parent = children.get(exposed.entity)
            if parent and exposed.draft_enabled:
                errors.append(
                    f"Service '{service.name}': '{exposed.entity}' is a composition "
                    f"child of '{parent}' and must set draftEnabled=false. CAP "
                    "draft-enables children through the root automatically."
                )


def _validate_apps(model: AppModel, errors: List[str]) -> None:
    services = {s.name: s for s in model.services}

    for app in model.apps:
        service = services.get(app.service)
        if service is None:
            errors.append(
                f"App '{app.id}' references unknown service '{app.service}'. "
                f"Known services: {sorted(services)}"
            )
            continue

        exposed = {e.exposed_name for e in service.entities}
        if app.main_entity not in exposed:
            errors.append(
                f"App '{app.id}': mainEntity '{app.main_entity}' is not exposed by "
                f"service '{app.service}'. Exposed: {sorted(exposed)}"
            )


def _validate_sample_data(model: AppModel, errors: List[str]) -> None:
    by_name = {e.name: e for e in model.entities}

    for entity_name, rows in model.sample_data.items():
        entity = by_name.get(entity_name)
        if entity is None:
            errors.append(
                f"sampleData has rows for unknown entity '{entity_name}'. "
                f"Known entities: {sorted(by_name)}"
            )
            continue

        # A to-one relation is stored as a foreign key column named <rel>_ID.
        allowed = set(_known_members(entity))
        for rel in entity.relations:
            if rel.cardinality is Cardinality.TO_ONE:
                allowed.add(rel.name + "_ID")

        for index, row in enumerate(rows):
            for column in row:
                if column not in allowed:
                    errors.append(
                        f"sampleData[{entity_name}][{index}]: column '{column}' is "
                        f"not a member of '{entity_name}'. Available: {sorted(allowed)}"
                    )
