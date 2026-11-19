"""FR-18: the block decision. Pure, no database."""

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from keepair.registry import (
    DenyReason,
    EffectiveStatus,
    ModelEntry,
    PolicySnapshot,
    RegistryError,
    Status,
    clean_reason,
    decide_block,
    effective_model_status,
)

pytestmark = pytest.mark.req("FR-18", "SEC-05")

STATUSES = list(Status)


def snapshot(vendor_status: Status, model_status: Status) -> PolicySnapshot:
    return PolicySnapshot.build(
        version=7,
        vendors={"vendor-x": vendor_status, "vendor-ok": Status.ALLOWED},
        models={
            "vendor-x/model-1": ModelEntry("vendor-x", model_status),
            "vendor-ok/model-1": ModelEntry("vendor-ok", Status.ALLOWED),
        },
        aliases={"x1": "vendor-x/model-1", "X-One ": "vendor-x/model-1"},
    )


NAMES_FOR_MODEL = ["vendor-x/model-1", "x1", "x-one"]
casing = st.sampled_from([str.lower, str.upper, str.title])
padding = st.sampled_from(["", " ", "\t", "  \n"])


@given(
    vendor_status=st.sampled_from(STATUSES),
    model_status=st.sampled_from(STATUSES),
    name=st.sampled_from(NAMES_FOR_MODEL),
    case=casing,
    left=padding,
    right=padding,
)
def test_blocked_vendor_denies_even_when_model_allowed(
    vendor_status, model_status, name, case, left, right
):
    """Every vendor x model status combination, through the canonical name and every alias."""
    decision = decide_block(snapshot(vendor_status, model_status), left + case(name) + right)
    expected_allowed = vendor_status is Status.ALLOWED and model_status is Status.ALLOWED
    assert decision.allowed is expected_allowed
    assert decision.snapshot_version == 7
    if vendor_status is Status.BLOCKED:
        assert decision.reason is DenyReason.VENDOR_BLOCKED  # vendor first, whatever the model says
    elif model_status is Status.BLOCKED:
        assert decision.reason is DenyReason.MODEL_BLOCKED
    else:
        assert decision.reason is None and decision.model_id == "vendor-x/model-1"


def test_every_status_combination_is_covered_exhaustively():
    for vendor_status, model_status, name in itertools.product(STATUSES, STATUSES, NAMES_FOR_MODEL):
        allowed = decide_block(snapshot(vendor_status, model_status), name).allowed
        assert allowed is (vendor_status is Status.ALLOWED and model_status is Status.ALLOWED)


@pytest.mark.parametrize("name", ["nope", "vendor-x/model-2", "", "  ", "vendor-x", "x1/extra"])
def test_unknown_alias_denies(name):
    decision = decide_block(snapshot(Status.ALLOWED, Status.ALLOWED), name)
    assert not decision.allowed and decision.reason is DenyReason.UNKNOWN_MODEL


@given(st.text(max_size=40))
def test_unknown_names_never_allowed(name):
    known = {"vendor-x/model-1", "x1", "x-one", "vendor-ok/model-1"}
    decision = decide_block(snapshot(Status.ALLOWED, Status.ALLOWED), name)
    assert decision.allowed is (name.strip().lower() in known)


def test_alias_to_blocked_model_denies():
    decision = decide_block(snapshot(Status.ALLOWED, Status.BLOCKED), "x1")
    assert not decision.allowed and decision.reason is DenyReason.MODEL_BLOCKED


def test_blocked_vendor_not_bypassed_by_model_alias():
    decision = decide_block(snapshot(Status.BLOCKED, Status.ALLOWED), "X-ONE")
    assert not decision.allowed and decision.reason is DenyReason.VENDOR_BLOCKED
    # A different vendor is not affected.
    assert decide_block(snapshot(Status.BLOCKED, Status.ALLOWED), "vendor-ok/model-1").allowed


def test_model_whose_vendor_is_missing_is_denied():
    snap = PolicySnapshot.build(1, {}, {"ghost/model": ModelEntry("ghost", Status.ALLOWED)}, {})
    assert decide_block(snap, "ghost/model").reason is DenyReason.UNKNOWN_MODEL


def test_snapshot_is_immutable():
    snap = snapshot(Status.BLOCKED, Status.ALLOWED)
    with pytest.raises(TypeError):
        snap.vendors["vendor-x"] = Status.ALLOWED
    with pytest.raises(AttributeError):
        snap.version = 8


@pytest.mark.req("UX-3", "FR-18")
def test_displayed_status_is_never_allowed_under_a_blocked_vendor():
    for vendor_status, model_status in itertools.product(STATUSES, STATUSES):
        shown = effective_model_status(vendor_status, model_status)
        allowed = decide_block(snapshot(vendor_status, model_status), "x1").allowed
        assert (
            shown is EffectiveStatus.ALLOWED
        ) is allowed  # the UI never disagrees with the decision
        if vendor_status is Status.BLOCKED:
            assert shown is EffectiveStatus.BLOCKED_BY_VENDOR


@pytest.mark.parametrize("bad", ["", "short", "   too short ", "x" * 301])
def test_block_reason_length_is_enforced(bad):
    with pytest.raises(RegistryError):
        clean_reason(bad)


def test_block_reason_is_trimmed_and_collapsed():
    assert clean_reason("  Contract   review\n in progress ") == "Contract review in progress"
