import pytest
import yaml
from pydantic import ValidationError

from keepair.help_registry import FieldHelp, HelpRegistry

pytestmark = pytest.mark.req("Information system (owner brief)", "UX-14")

BASE = {
    "name": "Cap",
    "meaning": "The most this budget may spend in the period.",
    "unit": "USD, micro-units / 1,000,000",
    "source": "user input",
    "source_detail": "Entered on the budget form.",
    "worked_example": {"description": "Demo budget.", "result": "1,000.00 USD"},
    "allowed_range": "0 or more",
    "validation": "Whole micro-units.",
    "prd_ref": "FR-04",
}


def make(**changes):
    return FieldHelp(id="x.y", **{**BASE, **changes})


def test_valid_entry_loads():
    assert make().name == "Cap"


@pytest.mark.parametrize("missing", ["unit", "meaning", "allowed_range", "validation", "prd_ref"])
def test_required_parts_cannot_be_missing_or_empty(missing):
    with pytest.raises(ValidationError):
        make(**{missing: ""})
    with pytest.raises(ValidationError):
        FieldHelp(id="x.y", **{k: v for k, v in BASE.items() if k != missing})


def test_meaning_is_two_sentences_at_most():
    with pytest.raises(ValidationError, match="two sentences"):
        make(meaning="One. Two. Three.")


def test_calculated_field_needs_formula_function_and_inputs():
    with pytest.raises(ValidationError, match="formula"):
        make(source="calculated")
    with pytest.raises(ValidationError, match="inputs"):
        make(source="calculated", formula="a = b", formula_fn="f")
    example = {"description": "d", "inputs": {"b": "1"}, "result": "1"}
    assert make(source="calculated", formula="a = b", formula_fn="f", worked_example=example)


def test_prd_reference_must_name_a_requirement():
    with pytest.raises(ValidationError, match="prd_ref"):
        make(prd_ref="see the docs")


def test_unknown_field_id_raises(tmp_path):
    path = tmp_path / "help.yaml"
    path.write_text(yaml.safe_dump({"fields": {"x.y": BASE}}))
    registry = HelpRegistry.load(path)
    assert registry.ids() == {"x.y"}
    with pytest.raises(KeyError, match="no help registry entry"):
        registry.get("nope")
