"""Template helpers that render fields with their "i" button.

Templates call these with a field ID. The helper looks the ID up in the help
registry (raising if it is missing) and remembers it, so the base template can
render one popover per field used on the page.
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

from keepair.help_registry import FieldHelp, HelpRegistry


def dom_id(field_id: str) -> str:
    return "help-" + re.sub(r"[^a-z0-9]+", "-", field_id.lower()).strip("-")


class HelpContext:
    def __init__(self, registry: HelpRegistry) -> None:
        self._registry = registry
        self._used: dict[str, FieldHelp] = {}

    def name(self, field_id: str) -> str:
        return self._registry.get(field_id).name

    def button(self, field_id: str) -> Markup:
        entry = self._registry.get(field_id)
        self._used[field_id] = entry
        return Markup(
            '<button type="button" class="info" popovertarget="{target}" '
            'data-help-for="{fid}" aria-label="About {name}">'
            '<span aria-hidden="true">i</span></button>'
        ).format(target=dom_id(field_id), fid=field_id, name=entry.name)

    def th(self, field_id: str) -> Markup:
        return Markup(
            '<th scope="col" data-field-id="{fid}"><span class="th">{name} {btn}</span></th>'
        ).format(fid=escape(field_id), name=self.name(field_id), btn=self.button(field_id))

    def used(self) -> list[tuple[str, FieldHelp]]:
        return [(dom_id(fid), entry) for fid, entry in self._used.items()]
