"""Fill in gaps LLMs commonly leave in an otherwise valid AppModel."""

from __future__ import annotations

from typing import Dict, List, Set

from .ir import AppModel, Cardinality, RelationKind

# Models sometimes invent a second OData service named after the IR field
# `entities`. That is not a real consumer — drop it before render/compile.
_BOGUS_SERVICE_NAMES = frozenset({"entities", "entity", "db", "schema", "service", "services"})


def _composition_children(model: AppModel) -> Set[str]:
    children: Set[str] = set()
    for entity in model.entities:
        for rel in entity.relations:
            if rel.kind is RelationKind.COMPOSITION and rel.cardinality is Cardinality.TO_MANY:
                children.add(rel.target)
    return children


def _referenced_targets(model: AppModel) -> Set[str]:
    """Entities that are only targets of to-one associations (typical read-only masters)."""
    targets: Set[str] = set()
    composers: Set[str] = set()
    for entity in model.entities:
        for rel in entity.relations:
            if rel.kind is RelationKind.COMPOSITION:
                composers.add(entity.name)
            if rel.cardinality is Cardinality.TO_ONE:
                targets.add(rel.target)
    # Prefer treating pure targets that never compose anything as reference data.
    return targets - composers - _composition_children(model)


def _exposure_key(item: Dict) -> str:
    return str(item.get("as") or item.get("entity") or "")


def _collapse_services(data: Dict) -> None:
    """Drop confused/unused extra services Gemini often invents."""
    services: List[Dict] = list(data.get("services") or [])
    if not services:
        return

    services = [
        s for s in services if str(s.get("name") or "").lower() not in _BOGUS_SERVICE_NAMES
    ]
    if not services:
        # All services were bogus — leave empty; validation will ask for one.
        data["services"] = []
        return

    if len(services) == 1:
        data["services"] = services
        return

    app_names = {
        a.get("service")
        for a in (data.get("apps") or [])
        if isinstance(a, dict) and a.get("service")
    }
    preferred = [s for s in services if s.get("name") in app_names]
    if not preferred:
        preferred = [
            max(services, key=lambda s: len(s.get("entities") or []))
        ]

    keep = preferred[0]
    seen = {_exposure_key(e) for e in (keep.get("entities") or []) if _exposure_key(e)}
    for other in services:
        if other.get("name") == keep.get("name"):
            continue
        for item in other.get("entities") or []:
            key = _exposure_key(item)
            if key and key not in seen:
                keep.setdefault("entities", []).append(item)
                seen.add(key)

    for app in data.get("apps") or []:
        if isinstance(app, dict) and app.get("service") != keep.get("name"):
            app["service"] = keep["name"]

    data["services"] = [keep]


def normalize_model(model: AppModel) -> AppModel:
    """Repair common LLM omissions without changing a sound model."""
    data = model.model_dump(by_alias=True)
    children = _composition_children(model)
    references = _referenced_targets(model)
    known = {e.name for e in model.entities}

    _collapse_services(data)

    for service in data.get("services") or []:
        requires = service.get("requires")
        if isinstance(requires, str):
            # Gemini sometimes pastes compiler HTML into this field.
            requires = requires.strip().split()[0] if requires.strip() else None
            if requires and (
                len(requires) > 64
                or "<" in requires
                or not requires.replace("-", "").replace("_", "").isalnum()
            ):
                requires = "authenticated-user"
            service["requires"] = requires

        path = service.get("path")
        if isinstance(path, str):
            path = path.strip().strip("/")
            if not path or len(path) > 64 or "<" in path:
                path = None
            service["path"] = path

        exposed = service.get("entities") or []
        if exposed:
            # Ensure composition children are not draft-enabled.
            for item in exposed:
                if item.get("entity") in children:
                    item["draftEnabled"] = False
            continue

        # Service declared with no exposures — wire every entity with sane defaults.
        wired: List[Dict] = []
        for entity in model.entities:
            is_child = entity.name in children
            is_ref = entity.name in references and entity.name not in children
            wired.append(
                {
                    "entity": entity.name,
                    "draftEnabled": (not is_child) and (not is_ref),
                    "readonly": is_ref,
                }
            )
        service["entities"] = wired

    # Drop sampleData rows for unknown entities rather than failing the whole run.
    sample = data.get("sampleData") or {}
    data["sampleData"] = {k: v for k, v in sample.items() if k in known}

    # If apps reference a service/entity that exists, leave them; if no apps but
    # we have a draft-enabled root, synthesize one so the project is runnable.
    if not data.get("apps") and data.get("services"):
        service = data["services"][0]
        main = None
        for item in service.get("entities") or []:
            if item.get("draftEnabled"):
                main = item.get("as") or item.get("entity")
                break
        if main is None and service.get("entities"):
            main = service["entities"][0].get("as") or service["entities"][0].get("entity")
        if main:
            data["apps"] = [
                {
                    "id": "".join(ch for ch in main.lower() if ch.isalnum())[:24] or "app",
                    "title": f"Manage {main}",
                    "description": model.description or main,
                    "service": service["name"],
                    "mainEntity": main,
                }
            ]

    return AppModel.model_validate(data)
