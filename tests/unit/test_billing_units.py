"""Pure parts of billing: finalization figures, allocation, join confidence, file parser."""

import uuid
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from keepair.billing import allocation as A
from keepair.billing.finalization import (
    SOURCES,
    Figure,
    Finalization,
    MixedFigures,
    billing_figure,
    gateway_figure,
)
from keepair.billing.focus import COLUMNS, MAX_BYTES, Quarantine, decimal_to_micros, parse
from keepair.demo import billing as demo

USAGE, INVOICE = SOURCES["vendor-a-usage"], SOURCES["vendor-a-invoice"]
P = [
    A.ProjectRef(uuid.UUID(int=1), "Build Assistant", "Platform"),
    A.ProjectRef(uuid.UUID(int=2), "Log Summarizer", "Platform"),
    A.ProjectRef(uuid.UUID(int=3), "Red Team", "Evaluation"),
]
RULE = A.Rule(uuid.UUID(int=9), "Platform shared cost", 10, date(2026, 1, 1), None,
              {"project": "shared-platform"}, (("Build Assistant", 6000), ("Log Summarizer", 4000)))  # fmt: skip
DAY = date(2026, 1, 5)


def allocate(tags, amount=1_000_000, rules=(RULE,), manual=None, day=DAY):
    return A.allocate(amount_micros=amount, tags=tags, charge_date=day, projects=P,
                      rules=list(rules), manual_project_id=manual)  # fmt: skip


# --- finalization -----------------------------------------------------------


@pytest.mark.req("FR-07", "UX-8")
def test_estimate_never_labelled_invoiced():
    """Whatever the gateway computes is ESTIMATED, and no operation turns it into a charge."""
    estimate = gateway_figure(500, "USD")
    assert estimate.state is Finalization.ESTIMATED
    invoiced = billing_figure(480, "USD", "INVOICED")
    reported = billing_figure(490, "USD", "PROVIDER_REPORTED")
    for other in (invoiced, reported):
        with pytest.raises(MixedFigures):
            _ = estimate + other
        with pytest.raises(MixedFigures):
            _ = other + estimate
    with pytest.raises(MixedFigures):
        _ = invoiced + reported
    assert (estimate + gateway_figure(1, "USD")) == Figure(501, "USD", Finalization.ESTIMATED)
    with pytest.raises(MixedFigures):
        _ = estimate + gateway_figure(1, "EUR")
    with pytest.raises(ValueError, match="never an estimate"):
        billing_figure(1, "USD", "ESTIMATED")  # a billing record cannot claim to be an estimate
    with pytest.raises(AttributeError):
        estimate.state = Finalization.INVOICED  # frozen
    # Each source may supply exactly one state: the usage export cannot deliver "invoiced".
    assert USAGE.state is Finalization.PROVIDER_REPORTED and INVOICE.state is Finalization.INVOICED


@pytest.mark.req("FR-07")
def test_a_usage_file_cannot_label_its_rows_invoiced():
    rows = demo.usage_rows()[:3]
    rows[1] = rows[1] | {"x_FinalizationState": "INVOICED"}
    with pytest.raises(Quarantine) as bad:
        parse(demo.render(rows), USAGE)
    assert bad.value.reasons == [
        "Row 3, x_FinalizationState: must be PROVIDER_REPORTED for this source."
    ]
    with pytest.raises(Quarantine):
        parse(demo.render([rows[0] | {"x_FinalizationState": "ESTIMATED"}]), INVOICE)


# --- allocation -------------------------------------------------------------


@given(
    amount=st.integers(0, 10**15), weights=st.lists(st.integers(0, 10_000), min_size=1, max_size=8)
)
@pytest.mark.req("FR-03 (allocation percentages reconcile to 100%)")
def test_allocation_shares_sum_to_100_percent(amount, weights):
    if sum(weights) == 0:
        with pytest.raises(ValueError):
            A.split_amount(amount, weights)
        return
    parts = A.split_amount(amount, weights)
    assert sum(parts) == amount  # nothing lost, nothing invented
    for part, weight in zip(parts, weights, strict=True):
        exact = amount * weight / sum(weights)
        assert abs(part - exact) < 1  # within one micro-unit of the exact share
        assert part >= 0 and (weight > 0 or part == 0)


@given(amount=st.integers(0, 10**12), tags=st.dictionaries(
    st.sampled_from(["team", "project", "agent", "customer", "junk"]),
    st.sampled_from(["Platform", "Build Assistant", "Red Team", "shared-platform", "nope", ""]), max_size=4))  # fmt: skip
@pytest.mark.req("FR-03 (every record is allocated or explicitly unallocated)")
def test_every_record_is_fully_accounted_for(amount, tags):
    facts = allocate(tags, amount)
    assert sum(f.amount_micros for f in facts) == amount
    for f in facts:
        assert f.state in {"ALLOCATED", "REVIEW", "UNMATCHED", "UNALLOCATED"}
        assert (
            (f.project_id is not None)
            == (f.state in {"ALLOCATED", "REVIEW"})
            == (f.confidence is not None)
        )
        assert A.treatment(f.join_confidence) == {"ALLOCATED": "ACCEPTED", "REVIEW": "REVIEW"}.get(
            f.state, "UNMATCHED"
        )


@pytest.mark.req("FR-03 (confidence)", "FR-06")
def test_direct_inferred_manual_and_the_queues():
    [direct] = allocate(
        {"team": "platform ", "project": "BUILD ASSISTANT", "agent": "a", "environment": "prod"}
    )
    assert (direct.state, direct.confidence, direct.join_confidence, direct.project_id) == (
        "ALLOCATED",
        "DIRECT",
        90,
        P[0].id,
    )
    split = allocate({"project": "shared-platform"}, 1_000_001)
    assert [(f.project_id, f.amount_micros, f.confidence) for f in split] == [
        (P[0].id, 600_001, "INFERRED"),
        (P[1].id, 400_000, "INFERRED"),
    ]
    assert all(f.rule_id == RULE.id and "60%" in split[0].explanation for f in split)
    [review] = allocate({"project": "Red Team"})
    assert (review.state, review.confidence, review.join_confidence) == ("REVIEW", "INFERRED", 70)
    [unmatched] = allocate({"team": "Growth", "project": "shadow-experiment"})
    assert (unmatched.state, unmatched.project_id, unmatched.join_confidence) == (
        "UNMATCHED",
        None,
        0,
    )
    [wrong_team] = allocate({"team": "Evaluation", "project": "Build Assistant"})
    assert (
        wrong_team.state == "UNMATCHED" and "does not own" in wrong_team.explanation
    )  # never guessed
    [untagged] = allocate({})
    assert untagged.state == "UNALLOCATED"
    [manual] = allocate({"team": "Growth", "project": "shadow-experiment"}, manual=P[2].id)
    assert (manual.state, manual.confidence, manual.project_id) == ("ALLOCATED", "MANUAL", P[2].id)


@pytest.mark.req("FR-06 (launch confidence thresholds)")
def test_join_threshold_boundaries():
    assert [A.treatment(c) for c in (69, 70, 89, 90)] == [
        "UNMATCHED",
        "REVIEW",
        "REVIEW",
        "ACCEPTED",
    ]
    assert A.treatment(0) == "UNMATCHED" and A.treatment(100) == "ACCEPTED"
    full = {
        "team": "t",
        "project": "p",
        "customer": "c",
        "application": "a",
        "agent": "g",
        "environment": "e",
    }
    assert A.exact_confidence(full) == 100
    assert A.exact_confidence({k: v for k, v in full.items() if k != "customer"}) == 95
    assert A.exact_confidence({"team": "t", "project": "p"}) == 90  # floored at 90
    assert A.FALLBACK_CONFIDENCE == 70 and A.treatment(A.FALLBACK_CONFIDENCE) == "REVIEW"


@pytest.mark.req("FR-03 (deterministic results, rule priorities, effective dates)")
def test_rules_are_deterministic_and_dated():
    second = A.Rule(uuid.UUID(int=8), "Other", 10, date(2026, 1, 1), None, {"project": "shared-platform"},
                    (("Red Team", 10_000),))  # fmt: skip
    for rules in (
        (RULE, second),
        (second, RULE),
    ):  # same priority: the lower id wins, whatever the order
        assert allocate({"project": "shared-platform"}, rules=rules)[0].rule_id == second.id
    first = A.Rule(
        uuid.UUID(int=99),
        "First",
        1,
        date(2026, 1, 1),
        None,
        {"project": "shared-platform"},
        (("Red Team", 1),),
    )
    assert (
        allocate({"project": "shared-platform"}, rules=(RULE, second, first))[0].rule_id == first.id
    )
    assert (
        allocate({"project": "shared-platform"}, day=date(2025, 12, 31))[0].state == "UNMATCHED"
    )  # not yet in force
    ghost = A.Rule(
        uuid.UUID(int=1),
        "Ghost",
        1,
        date(2026, 1, 1),
        None,
        {"project": "shared-platform"},
        (("No Such", 1),),
    )
    assert allocate({"project": "shared-platform"}, rules=(ghost, RULE))[0].rule_id == RULE.id


# --- the file parser (untrusted input) ---------------------------------------


@pytest.mark.req("FR-01", "FR-02", "Hard rule 3 (no float)")
def test_demo_usage_file_parses_exactly():
    parsed = parse(demo.render(demo.usage_rows()), USAGE)
    assert len(parsed.rows) == 431 and parsed.dropped_tag_keys == 0
    row = parsed.rows[0]
    assert isinstance(row.billed_micros, int) and row.currency == "USD" and row.revision == 1
    assert row.charge_date == date(2026, 1, 1) and row.billing_period == date(2026, 1, 1)
    assert decimal_to_micros("1315.366593") == 1_315_366_593 and decimal_to_micros("0") == 0
    assert decimal_to_micros("0.000001") == 1


@pytest.mark.req("SEC-28", "S-19", "T-13")
def test_malformed_invoice_quarantined():
    with pytest.raises(Quarantine) as bad:
        parse(demo.render(demo.broken_rows()), USAGE)
    assert bad.value.reasons == [
        "Row 3, BilledCost: must be a number, zero or more.",
        "Row 4, ChargePeriodStart: is not an ISO 8601 time.",
        "Row 5, Tags: is not JSON.",
        "Row 6, BilledCost: has more than 6 decimals.",
    ]
    assert "HYPERLINK" not in str(bad.value.reasons)  # cell content is never repeated


def one(**changes) -> bytes:
    return demo.render([demo.usage_rows()[0] | changes])


@pytest.mark.req("SEC-28", "SEC-27 (allowlisted metadata keys)")
@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "header row"),
        (b"a,b,c\n1,2,3\n", "header row"),
        (",".join(COLUMNS).encode() + b"\n", "no data rows"),
        (b"\xff\xfe\x00bad", "not UTF-8"),
        (",".join(COLUMNS).encode() + b"\n\x00,1\n", "binary data"),
        (b"x" * (MAX_BYTES + 1), "larger than 5 MB"),
        (one(BilledCost="1e400"), "BilledCost"),
        (one(BilledCost="NaN"), "BilledCost"),
        (one(BilledCost="12,50"), "BilledCost"),
        (one(BillingCurrency="usd"), "BillingCurrency"),
        (one(ChargePeriodStart="2026-01-01T00:00:00"), "has no timezone"),
        (one(ChargePeriodEnd="2026-01-01T00:00:00Z"), "after ChargePeriodStart"),
        (one(ProviderName="vendor-b"), "ProviderName"),
        (one(ChargeCategory="Credit"), "not supported yet"),
        (one(x_RecordKey="has space"), "x_RecordKey"),
        (one(x_Revision="0"), "x_Revision"),
        (one(x_Revision="1.5"), "x_Revision"),
        (one(Tags="[1,2]"), "JSON object"),
        (one(Tags='{"project": {"nested": 1}}'), "must be text"),
        (one(Tags='{"project": "' + "x" * 300 + '"}'), "must be text"),
        (one(SkuId="x" * 5000), "not valid CSV, or a field is too long"),
        (demo.render([demo.usage_rows()[0]] * 2), "appear twice"),
    ],
)
def test_bad_files_are_refused_with_a_reason(data, reason):
    with pytest.raises(Quarantine) as bad:
        parse(data, USAGE)
    assert reason in " ".join(bad.value.reasons)


@pytest.mark.req("SEC-27 (allowlisted metadata keys)")
def test_unknown_tag_keys_are_dropped_not_stored():
    parsed = parse(one(Tags='{"project":"Red Team","cost_center":"42","__proto__":"x"}'), USAGE)
    assert parsed.rows[0].tags == {"project": "Red Team"} and parsed.dropped_tag_keys == 2


@given(st.binary(max_size=400))
@pytest.mark.req("SEC-28 (fuzz test)")
def test_parser_only_ever_returns_rows_or_quarantines(data):
    for blob in (data, ",".join(COLUMNS).encode() + b"\n" + data):
        try:
            parsed = parse(blob, USAGE)
            assert all(r.billed_micros >= 0 for r in parsed.rows)
        except Quarantine as bad:
            assert bad.reasons and len(bad.reasons) <= 20


@given(st.lists(st.text(max_size=30), min_size=len(COLUMNS), max_size=len(COLUMNS)))
@pytest.mark.req("SEC-28 (fuzz test)")
def test_parser_survives_arbitrary_cell_content(cells):
    try:
        parse(demo.render([dict(zip(COLUMNS, cells, strict=True))]), USAGE)
    except Quarantine:
        pass


@pytest.mark.req("Hard rule 2 (deterministic demo data)", "Hard rule 1")
def test_committed_demo_billing_files_are_what_the_generator_writes():
    from keepair.config import REPO_ROOT

    generated = demo.generate()
    assert generated == demo.generate()
    for name, data in generated.items():
        assert (REPO_ROOT / "demo" / "billing" / name).read_bytes() == data, name
    text = generated[demo.USAGE_FILE].decode()
    assert "vendor-a" in text and "openai" not in text.lower() and "anthropic" not in text.lower()
