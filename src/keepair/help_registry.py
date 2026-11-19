"""The "i" information registry (ui/help/field_help.yaml).

All help text lives in the registry file. Templates ask for a field by its
stable ID and never carry help text themselves. An unknown ID raises, so a
field without help cannot be rendered.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Source = Literal["user input", "gateway", "provider export", "calculated", "seed script", "system"]
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
_PRD_REF = re.compile(r"\b(FR-\d{2}|UX-\d{1,2}|SEC-\d{2}|Section \d)")


class WorkedExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    inputs: dict[str, str] = Field(default_factory=dict)
    result: str = Field(min_length=1)


class FieldHelp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    source: Source
    source_detail: str = Field(min_length=1)
    formula: str | None = None
    formula_fn: str | None = None
    worked_example: WorkedExample
    allowed_range: str = Field(min_length=1)
    validation: str = Field(min_length=1)
    prd_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> FieldHelp:
        if len(_SENTENCE_END.findall(self.meaning)) > 2:
            raise ValueError(f"{self.id}: meaning must be two sentences at most")
        if not _PRD_REF.search(self.prd_ref):
            raise ValueError(f"{self.id}: prd_ref must name a PRD requirement or section")
        if self.source == "calculated":
            if not self.formula or not self.formula_fn:
                raise ValueError(f"{self.id}: calculated fields need formula and formula_fn")
            if not self.worked_example.inputs:
                raise ValueError(f"{self.id}: calculated fields need worked example inputs")
        elif self.formula or self.formula_fn:
            raise ValueError(f"{self.id}: only calculated fields may carry a formula")
        return self


class HelpRegistry:
    def __init__(self, entries: dict[str, FieldHelp]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, path: Path) -> HelpRegistry:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("fields"), dict):
            raise ValueError("field_help.yaml must contain a 'fields' mapping")
        return cls({fid: FieldHelp(id=fid, **body) for fid, body in raw["fields"].items()})

    def get(self, field_id: str) -> FieldHelp:
        try:
            return self._entries[field_id]
        except KeyError:
            raise KeyError(f"no help registry entry for field '{field_id}'") from None

    def ids(self) -> set[str]:
        return set(self._entries)

    def all(self) -> list[FieldHelp]:
        return list(self._entries.values())
