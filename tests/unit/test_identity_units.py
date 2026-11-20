"""Pure rules of phase 5 and 6: TOTP, passwords, permissions, approvals, kill switch, CSV."""

from datetime import UTC, datetime, timedelta
from itertools import product
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from keepair import approvals, audit, killswitch, owners, passwords, totp
from keepair.exports import FORMULA_STARTS, Amount, cell, neutralize, to_csv
from keepair.permissions import MATRIX, STEP_UP, Perm, Role, allowed
from keepair.rng import seeded_rng

RFC_SECRET = b"12345678901234567890"  # RFC 6238 appendix B, SHA-1


def at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


@pytest.mark.req("FR-13 (TOTP, offline-verifiable with a fixed secret)", "SEC-13")
@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"),
     (2000000000, "279037")],
)  # fmt: skip
def test_totp_matches_the_rfc_6238_test_vectors(seconds, expected):
    assert totp.code(RFC_SECRET, at(seconds)) == expected


@pytest.mark.req("FR-13", "SEC-13")
def test_totp_accepts_one_step_of_drift_and_nothing_more():
    now = at(1111111109)
    step = totp.step_of(now)
    for drift, accepted in ((-2, False), (-1, True), (0, True), (1, True), (2, False)):
        candidate = totp.code_at_step(RFC_SECRET, step + drift)
        assert (totp.verify(RFC_SECRET, candidate, now) is not None) is accepted
    assert totp.verify(RFC_SECRET, "08 1804", now) == step  # spaces are ignored
    for bad in ("", "08180", "0818045", "abcdef", "081805"):
        assert totp.verify(RFC_SECRET, bad, now) is None


@pytest.mark.req("SEC-13 (a code is accepted once)")
def test_totp_code_cannot_be_replayed():
    now = at(1111111109)
    candidate = totp.code(RFC_SECRET, now)
    step = totp.verify(RFC_SECRET, candidate, now, last_step=0)
    assert step is not None
    assert totp.verify(RFC_SECRET, candidate, now, last_step=step) is None
    later = now + timedelta(seconds=30)
    assert totp.verify(RFC_SECRET, totp.code(RFC_SECRET, later), later, last_step=step) == step + 1


@pytest.mark.req("FR-13")
def test_new_totp_secret_is_160_bits_and_types_into_an_authenticator():
    secret = totp.new_secret(seeded_rng(1))
    assert len(secret) == 20 and secret != totp.new_secret(seeded_rng(2))
    assert len(totp.to_base32(secret)) == 32 and totp.to_base32(secret).isalnum()


@pytest.mark.req("SEC-13 (NIST SP 800-63B password rules)")
def test_password_rules_are_length_and_a_block_list_not_composition():
    passwords.check_rules("correct horse battery")  # long, no digit or symbol: accepted
    for bad in ("short", "x" * 129, "password1234", "aaaaaaaaaaaaaa", "alice.admin-2026!"):
        with pytest.raises(passwords.WeakPassword):
            passwords.check_rules(bad, username="alice.admin")


@pytest.mark.req("SEC-13", "Hard rule 8 (secrets are stored as hashes)")
def test_password_is_stored_as_a_salted_scrypt_hash():
    rng = seeded_rng(7)
    stored = passwords.hash_password("correct horse battery", passwords.new_salt(rng))
    other = passwords.hash_password("correct horse battery", passwords.new_salt(rng))
    assert stored.startswith("scrypt$15$8$3$") and "correct" not in stored
    assert stored != other  # a new salt each time
    assert passwords.verify_password("correct horse battery", stored)
    assert not passwords.verify_password("correct horse batterx", stored)
    for garbage in ("", "scrypt$1$2", "bcrypt$15$8$3$AAAA$AAAA", "scrypt$x$8$3$AAAA$AAAA"):
        assert not passwords.verify_password("anything-at-all", garbage)
    generated = passwords.generate_password(rng)
    passwords.check_rules(generated)
    assert len(generated) == 20


@pytest.mark.req("FR-13 (permission matrix, tested exhaustively)", "SEC-14")
def test_permission_matrix_is_complete_and_least_privilege():
    assert set(MATRIX) == set(Perm)
    for perm, role in product(Perm, Role):
        assert allowed(role, perm) is (role in MATRIX[perm])
    # What only an administrator may do.
    admin_only = {
        Perm.BLOCK, Perm.MANAGE_BUDGETS, Perm.REQUEST_TWO_PERSON, Perm.DECIDE_TWO_PERSON,
        Perm.KILL_SWITCH, Perm.MANAGE_USERS, Perm.MANAGE_CREDENTIALS, Perm.ACK_FAIL_OPEN,
        Perm.DEMO_CONSOLE, Perm.CANCEL_REQUEST,
    }  # fmt: skip
    for perm in admin_only:
        assert MATRIX[perm] == {Role.ADMIN}
    # The auditor reads everything and changes nothing.
    auditor = {p for p in Perm if allowed(Role.AUDITOR, p)}
    assert auditor == {Perm.PUBLIC, Perm.VIEW, Perm.VIEW_ADMIN, Perm.VIEW_AUDIT,
                       Perm.VERIFY_AUDIT, Perm.EXPORT_REPORTS}  # fmt: skip
    assert not allowed(Role.ENGINEERING, Perm.MANAGE_BILLING)
    assert not allowed(Role.FINANCE, Perm.VIEW_AUDIT)
    assert not allowed("OWNER", Perm.VIEW) and not allowed(Role.ADMIN, "made_up")
    # Every action that changes policy asks for a fresh code.
    no_policy_change = {Perm.MANAGE_CREDENTIALS, Perm.ACK_FAIL_OPEN, Perm.DEMO_CONSOLE,
                        Perm.CANCEL_REQUEST}  # fmt: skip
    assert admin_only - no_policy_change == STEP_UP


A, B_, C = UUID(int=1), UUID(int=2), UUID(int=3)


@pytest.mark.req("SEC-15", "FR-11")
def test_self_approval_denied():
    assert not approvals.may_decide(A, A, Role.ADMIN)  # the requester
    assert approvals.may_decide(A, B_, Role.ADMIN)  # a different administrator
    for role in (Role.FINANCE, Role.ENGINEERING, Role.AUDITOR):
        assert not approvals.may_decide(A, B_, role)  # the second person must hold ADMIN


@pytest.mark.req("FR-11 (requester cannot approve own request)", "SEC-15")
def test_held_request_eligibility():
    eligible = approvals.held_eligibility
    # The owner of the requesting project is the requesting side, whatever their role.
    assert eligible(A, Role.ADMIN, A, [B_]) == "SELF_APPROVAL"
    assert eligible(A, Role.ENGINEERING, A, [A]) == "SELF_APPROVAL"
    assert eligible(B_, Role.ADMIN, A, [None]) is None  # any other administrator
    assert eligible(B_, Role.FINANCE, A, [B_, None]) is None  # owner of a budget above
    assert eligible(C, Role.FINANCE, A, [B_]) == "NOT_ELIGIBLE"
    assert eligible(C, Role.ENGINEERING, None, []) == "NOT_ELIGIBLE"


@pytest.mark.req("FR-17", "SEC-15")
def test_which_budget_changes_need_a_second_person():
    assert owners.owner_change_needs_second_person("HARD", A)
    assert not owners.owner_change_needs_second_person("HARD", None)  # first owner
    assert not owners.owner_change_needs_second_person("SOFT", A)
    for old, new in product(owners.POLICIES, owners.POLICIES):
        weakens = old in ("HARD", "APPROVAL") and new in ("MONITOR", "SOFT")
        assert owners.policy_change_needs_second_person(old, new) is weakens


@pytest.mark.req("FR-22 (kill switch scopes)", "SEC-08")
def test_kill_switch_scope_rule():
    project, other = UUID(int=10), UUID(int=11)
    assert not killswitch.affects(frozenset(), project, "vendor-a")
    assert killswitch.affects(frozenset({("GLOBAL", "")}), project, None)
    assert killswitch.affects(frozenset({("PROJECT", str(project))}), project, "vendor-a")
    assert not killswitch.affects(frozenset({("PROJECT", str(other))}), project, "vendor-a")
    assert killswitch.affects(frozenset({("VENDOR", "vendor-a")}), project, "vendor-a")
    assert not killswitch.affects(frozenset({("VENDOR", "vendor-b")}), project, "vendor-a")
    assert not killswitch.affects(frozenset({("VENDOR", "vendor-a")}), project, None)


@pytest.mark.req("UX-7 (impact preview)")
def test_kill_switch_impact_counts():
    from types import SimpleNamespace as D

    now = datetime(2026, 1, 15, 9, tzinfo=UTC)
    old, new = now - timedelta(minutes=30), now - timedelta(minutes=1)
    decisions = [
        D(project="P1", agent="a1", model_id="vendor-a/model-1", occurred_at=new),
        D(project="P1", agent="a1", model_id="vendor-a/model-2", occurred_at=old),
        D(project="P2", agent="a2", model_id="vendor-b/model-1", occurred_at=new),
        D(project="P3", agent="a3", model_id=None, occurred_at=new),  # unknown model
    ]
    since = now - timedelta(minutes=5)
    assert killswitch.count_impact(decisions, "GLOBAL", "", "", since) == (3, 3, 3)
    assert killswitch.count_impact(decisions, "VENDOR", "vendor-a", "", since) == (1, 1, 1)
    assert killswitch.count_impact(decisions, "PROJECT", "", "P2", since) == (1, 1, 1)
    assert killswitch.count_impact(decisions, "VENDOR", "vendor-c", "", since) == (0, 0, 0)


@pytest.mark.req("SEC-32 (hash chain)")
def test_audit_hash_covers_every_field_and_the_previous_hash():
    base = {"seq": 1, "actor": "alice.admin", "action": "registry.blocked", "reason": "Why."}
    first = audit.row_hash(audit.GENESIS, base)
    assert len(first) == 32 and first == audit.row_hash(audit.GENESIS, dict(reversed(base.items())))
    for key in base:
        changed = {**base, key: "other" if key != "seq" else 2}
        assert audit.row_hash(audit.GENESIS, changed) != first
    assert audit.row_hash(first, base) != first  # a different previous record


@pytest.mark.req("SEC-29 (CSV formula neutralization)")
@pytest.mark.parametrize("start", ["=", "+", "-", "@", "\uff20", "\t", "\r"])
def test_csv_formula_neutralized(start):
    payload = f'{start}HYPERLINK("http://evil.example","x")'
    assert neutralize(payload) == "'" + payload
    assert neutralize("  " + payload).startswith("'")  # leading spaces do not hide it
    assert cell(payload).startswith("'")
    line = to_csv(["Owner"], [[payload]]).splitlines()[1]
    assert line.startswith("\"'")  # quoted, and the first character of the cell is the apostrophe


@pytest.mark.req("SEC-29")
def test_csv_leaves_ordinary_text_and_exact_amounts_alone():
    assert neutralize("Fiona Marchetti") == "Fiona Marchetti"
    assert neutralize("a=b+c-d@e") == "a=b+c-d@e"  # only the start of a cell matters
    assert cell(None) == ""
    assert cell(Amount(21_915_330_000)) == "21915.330000"
    assert cell(Amount(-1_500_000)) == "-1.500000"  # a number, written by us, stays a number
    assert cell(Amount(7)) == "0.000007"
    text = to_csv(["A", "B"], [["x", Amount(1_000_000)], ['say "hi"', None]])
    assert text == '"A","B"\r\n"x","1.000000"\r\n"say ""hi""",""\r\n'


@pytest.mark.req("SEC-29")
@given(st.text(max_size=40))
def test_no_text_cell_can_start_a_formula(value):
    out = neutralize(value)
    assert not out.startswith(FORMULA_STARTS)
    assert not out.lstrip(" ").startswith(FORMULA_STARTS) or out.startswith("'")
    assert out in (value, "'" + value)
