"""Prompt construction for spec -> IR generation.

The JSON schema does the structural work, so the prompt only carries the CAP
domain conventions a schema can't express: when to use a composition versus an
association, how many columns belong in a list report, how draft works.
"""

from __future__ import annotations

import json
from typing import List, Optional

SYSTEM_PROMPT = """\
You are a senior SAP CAP architect. You read a functional specification and \
produce a structured application model that a deterministic code generator \
turns into a CAP project (CDS schema, OData service, Fiori elements \
annotations, sample data and tests).

You never write CDS source. You only emit the structured model. The generator \
handles all syntax.

MODELLING CONVENTIONS

1. Entity names are PascalCase and plural: `PurchaseOrders`, not \
`PurchaseOrder` or `purchase_orders`. Field names are camelCase.

2. Use `useCuid: true` (a generated UUID key) unless the spec demands a \
specific business key. Use `useManaged: true` on entities users create or edit, \
so created/modified tracking comes for free. Pure line-item entities usually \
need cuid but not managed.

3. Parent-child ownership, where the child cannot exist alone (order and its \
items), is a `composition`. A reference to an independent entity (order to \
supplier) is an `association`. Getting this wrong is the most common and most \
damaging modelling error, so decide it deliberately for every relationship.

4. Every to-many relation needs a `backlink`: the name of the to-one relation \
on the target that points back. Always declare that to-one relation on the \
child as well. A composition child's back-reference should be `notNull: true`.

5. Prefer `Decimal` with explicit precision and scale for money and quantities, \
never `Double`. Amounts are typically `Decimal(15, 2)`; quantities \
`Decimal(13, 3)`. Use `Date` for calendar dates and `Timestamp` for instants.

6. Give every field a human-readable `label`. These become the column and form \
labels in the UI, so write them the way a business user would say them.

7. Status-like fields should use `enum` with UPPER_SNAKE codes as keys and \
readable labels as values. Codes must be valid identifiers.

SERVICE RULES

8. Expose domain entities through exactly one OData service unless the spec \
clearly describes separate consumers. Every service MUST include a non-empty \
`entities` array naming each exposed entity with draftEnabled / readonly \
flags. Never create a service named `entities`, `entity`, `db`, or `schema` \
— those words refer to model fields / CDS folders, not service names. Prefer \
a name like `TravelService` or `ExpenseService`.

9. Set `draftEnabled: true` only on the root entity users edit. A composition \
child MUST have `draftEnabled: false` — CAP draft-enables children through the \
root automatically, and setting it on a child is a compile error.

10. Reference data the app only reads should be `readonly: true` with \
`draftEnabled: false`.

UI RULES

11. Give the main entity a full `ui` block. Also give a `ui` block with a \
`lineItem` to any composition child, otherwise its table on the object page \
cannot be rendered.

12. `lineItem` should hold five to eight of the most identifying columns, in \
the order a user scanning a list would want them. Do not dump every field in.

13. `selectionFields` are the filter bar: two to four fields someone would \
actually filter by, such as identifier, status, date and the main reference.

14. Group the remaining fields into two to four `fieldGroups` with meaningful \
labels ("General Information", "Commercial", "Delivery"). Together the field \
groups should cover essentially all editable fields.

15. To show a referenced entity in a list, put the association's name in \
`lineItem` (for example `supplier`). The generator resolves it to a readable \
path automatically. Never reference a foreign key column like `supplier_ID` in \
a UI list.

SAMPLE DATA

16. Provide two to four realistic rows per entity. Realistic means plausible \
business content in the spec's domain, not "Test 1" and "Foo".

17. Every row of an entity with `useCuid` must include an explicit `ID` holding \
a valid UUID string. Reference a parent with the foreign key column \
`<relationName>_ID` and a UUID that actually appears in that parent's rows.

18. Write all values as strings. Dates use `YYYY-MM-DD`. Decimals use a plain \
decimal point and match the declared scale.

Model exactly what the specification describes. Do not invent whole entities \
the spec never mentions. Where the spec is silent on something structurally \
required — a key, a label, a status list — choose the conventional SAP answer \
and move on.\
"""


def build_user_prompt(spec_text: str, project_name: Optional[str] = None) -> str:
    hint = (
        f"\n\nUse '{project_name}' as the projectName.\n" if project_name else "\n"
    )
    return (
        "Here is the functional specification.\n\n"
        "<specification>\n"
        f"{spec_text.strip()}\n"
        "</specification>"
        f"{hint}"
        "Produce the application model."
    )


def build_repair_prompt(errors: List[str], stage: str) -> str:
    """Feedback turn after validation or compilation rejected the model."""
    listing = "\n".join(f"  {i + 1}. {e}" for i, e in enumerate(errors))

    if stage == "compile":
        preamble = (
            "The generated project was rejected by the CDS compiler. These are "
            "the compiler diagnostics, mapped back to the model where possible:"
        )
    else:
        preamble = (
            "The model you produced failed validation. These are the problems:"
        )

    hint = ""
    joined = "\n".join(errors).lower()
    if "multiple service" in joined:
        hint = (
            "\n\nIf the compiler reported multiple service definitions, keep "
            "exactly one OData service (the one the Fiori app uses). Do not "
            "emit a second service named `entities`."
        )

    return (
        f"{preamble}\n\n{listing}\n\n"
        "Produce a corrected application model. Return the complete model, not "
        "a patch, and change only what is needed to resolve these problems."
        f"{hint}"
    )


def schema_summary(schema: dict) -> str:
    """Compact JSON schema rendering, for providers that take it in the prompt."""
    return json.dumps(schema, indent=2)
