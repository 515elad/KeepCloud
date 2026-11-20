"""Accounts, owners, approvals, two-person actions and the kill switch (phase 5)."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from keepair import approvals, iam, killswitch, owners, totp
from keepair.demo.seed import DEMO_PASSWORD, demo_clock, demo_totp_secret
from keepair.gateway import ledger
from keepair.registry import add_block
from keepair.rng import seeded_rng, system_rng
from keepair.schema import audit_log, budgets, sessions, users, vendors

REASON = "Agreed in the weekly review."
BOX = iam.SecretBox(iam.DEV_MFA_KEY)


def actor(engine, username: str) -> iam.Actor:
    with engine.connect() as conn:
        u = conn.execute(select(users).where(users.c.username == username)).one()
    return iam.Actor(u.id, u.tenant_id, u.username, u.display_name, u.role)


def tenant_of(engine):
    return actor(engine, "alice.admin").tenant_id


def code_for(username: str, clock) -> str:
    return totp.code(demo_totp_secret(username), clock.now())


def actions(engine) -> list[str]:
    with engine.connect() as conn:
        return list(conn.execute(select(audit_log.c.action).order_by(audit_log.c.seq)).scalars())


def reserved_matches_open_reservations(gw) -> bool:
    """Invariant: a budget's reserved amount is exactly its open reservations."""
    rows = gw.rows(
        "SELECT b.reserved_micros, coalesce(sum(r.reserved_micros), 0) AS open "
        "FROM budgets b LEFT JOIN reservations r ON b.id = ANY(r.budget_path) "
        "AND r.state IN ('RESERVED','HELD','APPROVED') GROUP BY b.id"
    )
    return all(r.reserved_micros == r.open for r in rows)


# --- Sign-in (FR-13, SEC-13) ---------------------------------------------------------


@pytest.mark.req("FR-13", "SEC-13")
def test_sign_in_needs_the_password_and_then_the_code(engine):
    clock, rng = demo_clock(), system_rng()
    with engine.begin() as conn:
        assert iam.sign_in_password(conn, clock, rng, "alice.admin", "wrong-password-x") is None
        assert iam.sign_in_password(conn, clock, rng, "nobody.here", DEMO_PASSWORD) is None
        token = iam.sign_in_password(conn, clock, rng, " Alice.Admin ", DEMO_PASSWORD)
        assert token and iam.pending_username(conn, clock, token) == "alice.admin"
        assert iam.authenticate(conn, clock, token) is None  # the password alone is not enough
        assert iam.sign_in_code(conn, clock, BOX, token, "000000") is None
        assert iam.authenticate(conn, clock, token) is None
        signed_in = iam.sign_in_code(conn, clock, BOX, token, code_for("alice.admin", clock))
        assert signed_in.username == "alice.admin" and signed_in.role == "ADMIN"
        assert iam.authenticate(conn, clock, token).id == signed_in.id
        assert iam.authenticate(conn, clock, token + "x") is None
        assert iam.authenticate(conn, clock, None) is None
        # Only the hash of the token is stored.
        stored = conn.execute(select(sessions.c.token_hash)).scalars().all()
        assert all(len(bytes(h)) == 32 and token.encode() not in bytes(h) for h in stored)
    assert actions(engine)[-3:] == ["auth.sign_in_failed", "auth.sign_in_failed", "auth.sign_in"]


@pytest.mark.req("SEC-13")
def test_code_step_must_follow_the_password_within_five_minutes(engine):
    clock, rng = demo_clock(), system_rng()
    with engine.begin() as conn:
        token = iam.sign_in_password(conn, clock, rng, "bob.admin", DEMO_PASSWORD)
        clock.advance(timedelta(seconds=iam.PENDING_S + 1))
        assert iam.pending_username(conn, clock, token) is None
        assert iam.sign_in_code(conn, clock, BOX, token, code_for("bob.admin", clock)) is None


@pytest.mark.req("SEC-13 (lockout)", "SEC-17")
def test_account_locks_after_five_failures_and_opens_again_later(engine):
    clock, rng = demo_clock(), system_rng()
    with engine.begin() as conn:
        for _ in range(iam.MAX_FAILED):
            assert iam.sign_in_password(conn, clock, rng, "bob.admin", "wrong-password-x") is None
        assert iam.is_locked(conn, clock, "bob.admin")
        # The right password is refused while locked, with the same answer.
        assert iam.sign_in_password(conn, clock, rng, "bob.admin", DEMO_PASSWORD) is None
        clock.advance(timedelta(seconds=iam.LOCK_S + 1))
        assert not iam.is_locked(conn, clock, "bob.admin")
        assert iam.sign_in_password(conn, clock, rng, "bob.admin", DEMO_PASSWORD)
    with engine.connect() as conn:
        last_failure = conn.execute(
            select(audit_log.c.after)
            .where(audit_log.c.action == "auth.sign_in_failed")
            .order_by(audit_log.c.seq.desc())
            .limit(1)
        ).scalar_one()
    assert last_failure == {"step": "password", "locked": True}


@pytest.mark.req("SEC-13 (idle and absolute session limits)")
def test_session_timeouts(engine):
    clock = demo_clock()
    user = actor(engine, "fiona.finance")
    with engine.begin() as conn:
        token = iam.create_session(conn, clock, system_rng(), user.id)
        clock.advance(timedelta(seconds=iam.IDLE_S - 60))
        assert iam.authenticate(conn, clock, token)  # used within 30 minutes: stays alive
        clock.advance(timedelta(seconds=iam.IDLE_S + 1))
        assert iam.authenticate(conn, clock, token) is None  # idle for over 30 minutes
        assert conn.execute(select(sessions.c.user_id)).first() is None  # and removed

        token = iam.create_session(conn, clock, system_rng(), user.id)
        for _ in range(iam.ABSOLUTE_S // (20 * 60)):
            clock.advance(timedelta(minutes=20))
            assert iam.authenticate(conn, clock, token)  # kept busy for 12 hours
        clock.advance(timedelta(minutes=20))
        assert iam.authenticate(conn, clock, token) is None  # the absolute limit ends it


@pytest.mark.req("SEC-13 (step-up)", "SEC-13 (a code is accepted once)")
def test_step_up_accepts_a_fresh_code_once(engine):
    clock = demo_clock()
    alice = actor(engine, "alice.admin")
    with engine.begin() as conn:
        good = code_for("alice.admin", clock)
        assert not iam.step_up(conn, clock, BOX, alice, "")
        assert iam.step_up(conn, clock, BOX, alice, good)
        assert not iam.step_up(conn, clock, BOX, alice, good)  # replay
        assert iam.demo_code(conn, clock, BOX, alice.id) != good  # the helper moves on
        assert iam.step_up(conn, clock, BOX, alice, iam.demo_code(conn, clock, BOX, alice.id))
        assert iam.demo_code(conn, clock, BOX, alice.id) is None  # two steps ahead: wait
        clock.advance(timedelta(seconds=60))
        assert iam.step_up(conn, clock, BOX, alice, code_for("alice.admin", clock))
        # Someone else's code is not mine.
        clock.advance(timedelta(seconds=30))
        assert not iam.step_up(conn, clock, BOX, alice, code_for("bob.admin", clock))


@pytest.mark.req("FR-13 (stored secrets)", "SEC-23 (no demo key in production)")
def test_totp_secret_is_encrypted_at_rest_and_bound_to_the_user(engine):
    alice, bob = actor(engine, "alice.admin"), actor(engine, "bob.admin")
    with engine.connect() as conn:
        stored = bytes(
            conn.execute(select(users.c.totp_secret_enc).where(users.c.id == alice.id)).scalar_one()
        )
    secret = demo_totp_secret("alice.admin")
    assert secret not in stored and BOX.open(stored, alice.id) == secret
    assert BOX.open(stored, bob.id) is None  # moved to another user's row: refused
    assert iam.SecretBox(bytes(32)).open(stored, alice.id) is None  # wrong key
    with pytest.raises(iam.MissingMfaKey):
        iam.load_mfa_key(None, "prod")
    assert iam.load_mfa_key(None, "demo") == iam.DEV_MFA_KEY


@pytest.mark.req("FR-13 (local-account lifecycle)", "SEC-17")
def test_create_disable_and_reset_a_user(engine):
    clock, rng = demo_clock(), seeded_rng(5)
    alice = actor(engine, "alice.admin")
    tenant = alice.tenant_id
    with engine.begin() as conn:
        for bad in ({"username": "X"}, {"username": "alice.admin"}, {"role": "OWNER"},
                    {"display_name": " "}, {"display_name": "x" * 81}):  # fmt: skip
            fields = {"username": "new.person", "display_name": "New Person", "role": "AUDITOR"}
            with pytest.raises(iam.IamError):
                iam.create_user(conn, clock, rng, BOX, tenant_id=tenant, actor=alice,
                                **{**fields, **bad})  # fmt: skip
        made = iam.create_user(conn, clock, rng, BOX, tenant_id=tenant, username="New.Person",
                               display_name="New  Person", role="AUDITOR", actor=alice)  # fmt: skip
        assert made.username == "new.person" and len(made.password) == 20
        token = iam.sign_in_password(conn, clock, rng, "new.person", made.password)
        row = conn.execute(select(users).where(users.c.id == made.user_id)).one()
        assert made.password not in row.password_hash and row.display_name == "New Person"
        secret = BOX.open(row.totp_secret_enc, made.user_id)
        assert totp.to_base32(secret) == made.totp_secret
        assert iam.sign_in_code(conn, clock, BOX, token, totp.code(secret, clock.now()))

        with pytest.raises(iam.IamError, match="your own account"):
            iam.set_status(conn, clock, tenant_id=tenant, user_id=alice.id, status="DISABLED",
                           actor=alice)  # fmt: skip
        iam.set_status(conn, clock, tenant_id=tenant, user_id=made.user_id, status="DISABLED",
                       actor=alice)  # fmt: skip
        assert iam.authenticate(conn, clock, token) is None  # sessions ended at once
        assert iam.sign_in_password(conn, clock, rng, "new.person", made.password) is None
        iam.set_status(conn, clock, tenant_id=tenant, user_id=made.user_id, status="ACTIVE",
                       actor=alice)  # fmt: skip
        again = iam.reset_credentials(conn, clock, rng, BOX, tenant_id=tenant,
                                      user_id=made.user_id, actor=alice)  # fmt: skip
        assert again.password != made.password and again.totp_secret != made.totp_secret
        assert iam.sign_in_password(conn, clock, rng, "new.person", made.password) is None
        assert iam.sign_in_password(conn, clock, rng, "new.person", again.password)
    assert [a for a in actions(engine) if a.startswith("user.")][-4:] == [
        "user.created", "user.disabled", "user.enabled", "user.credentials_reset",
    ]  # fmt: skip


# --- Owners (FR-17) ------------------------------------------------------------------


@pytest.mark.req("FR-17", "FR-05 (NO_OWNER)")
def test_hard_limit_without_owner_cannot_activate(gw):
    clock, engine = gw.clock, gw.engine
    alice, tenant = actor(engine, "alice.admin"), tenant_of(engine)
    call_notes = gw.budget("Call Notes")
    assert call_notes.owner_user_id is None and call_notes.policy == "MONITOR"
    apply = dict(tenant_id=tenant, actor="alice.admin", actor_id=alice.id, reason=REASON)
    with engine.begin() as conn, pytest.raises(owners.OwnerError) as refused:
        owners.apply_policy(conn, clock, budget_id=call_notes.id, policy="HARD", **apply)
    assert refused.value.code == "NO_OWNER"
    # The database refuses it too, whatever writes the row.
    with pytest.raises(IntegrityError, match="NO_OWNER"):
        gw.execute("UPDATE budgets SET policy = 'HARD' WHERE id = :id", id=call_notes.id)
    with pytest.raises(IntegrityError, match="NO_OWNER"):
        gw.execute("UPDATE budgets SET owner_user_id = NULL WHERE id = :id",
                   id=gw.budget("Build Assistant").id)  # fmt: skip
    assert gw.budget("Call Notes").policy == "MONITOR"

    bob = actor(engine, "bob.admin")
    with engine.begin() as conn:
        owners.apply_owner(conn, clock, budget_id=call_notes.id, user_id=bob.id, **apply)
        owners.apply_policy(conn, clock, budget_id=call_notes.id, policy="HARD", **apply)
    after = gw.budget("Call Notes")
    assert (after.policy, after.fail_mode, after.owner_user_id) == ("HARD", "FAIL_CLOSED", bob.id)
    assert actions(engine)[-2:] == ["budget.owner_changed", "budget.policy_changed"]


@pytest.mark.req("FR-17 (an agent cannot be an owner)")
def test_agent_cannot_be_owner(gw):
    engine = gw.engine
    [agent] = gw.rows("SELECT id FROM agents WHERE name = 'research-agent'")
    with engine.begin() as conn, pytest.raises(owners.OwnerError) as refused:
        owners.check_owner_change(conn, tenant_of(engine), gw.budget("Call Notes").id, agent.id)
    assert refused.value.code == "NOT_A_USER"
    with pytest.raises(IntegrityError, match="budgets_owner_fkey"):
        gw.execute("UPDATE budgets SET owner_user_id = :a WHERE id = :id", a=agent.id,
                   id=gw.budget("Call Notes").id)  # fmt: skip


@pytest.mark.req("FR-17 (the owner of a hard limit must be active)", "SEC-17")
def test_owner_of_a_hard_limit_cannot_be_disabled(gw):
    engine, clock = gw.engine, gw.clock
    alice, bob = actor(engine, "alice.admin"), actor(engine, "bob.admin")
    with engine.begin() as conn, pytest.raises(iam.IamError, match="hard-limit budget"):
        iam.set_status(conn, clock, tenant_id=alice.tenant_id, user_id=bob.id, status="DISABLED",
                       actor=alice)  # fmt: skip
    with pytest.raises(IntegrityError, match="OWNS_HARD_LIMIT"):
        gw.execute("UPDATE users SET status = 'DISABLED' WHERE id = :id", id=bob.id)
    fiona = actor(engine, "fiona.finance")  # owns soft and approval budgets only
    with engine.begin() as conn:
        iam.set_status(conn, clock, tenant_id=alice.tenant_id, user_id=fiona.id,
                       status="DISABLED", actor=alice)  # fmt: skip


@pytest.mark.req("FR-17", "SEC-15")
def test_owner_change_on_hard_limit_requires_second_admin(gw):
    engine, clock, rng = gw.engine, gw.clock, system_rng()
    alice, bob, fiona = (actor(engine, n) for n in ("alice.admin", "bob.admin", "fiona.finance"))
    omar = actor(engine, "omar.owner")
    budget = gw.budget("Build Assistant")
    assert budget.policy == "HARD" and budget.owner_user_id == omar.id
    change = dict(tenant_id=alice.tenant_id, budget_id=budget.id, budget_name="Build Assistant")
    with engine.begin() as conn:
        approval_id = approvals.change_owner(conn, clock, rng, user_id=bob.id, actor=alice,
                                             reason=REASON, **change)  # fmt: skip
    assert approval_id is not None and gw.budget("Build Assistant").owner_user_id == omar.id
    decide = dict(tenant_id=alice.tenant_id, approval_id=approval_id, approve=True)
    for who, code in ((alice, "SELF_APPROVAL"), (fiona, "NOT_ELIGIBLE")):
        with engine.begin() as conn, pytest.raises(approvals.ApprovalError) as refused:
            approvals.decide(conn, clock, actor=who, **decide)
        assert refused.value.code == code
    assert gw.budget("Build Assistant").owner_user_id == omar.id
    with engine.begin() as conn:
        assert approvals.decide(conn, clock, actor=bob, **decide) == "APPROVED"
    assert gw.budget("Build Assistant").owner_user_id == bob.id
    assert actions(engine)[-3:] == [
        "owner_change.requested", "budget.owner_changed", "owner_change.approved",
    ]  # fmt: skip
    # A first owner on a budget that is not a hard limit needs nobody else.
    with engine.begin() as conn:
        assert approvals.change_owner(
            conn, clock, rng, tenant_id=alice.tenant_id, budget_id=gw.budget("Call Notes").id,
            budget_name="Call Notes", user_id=fiona.id, actor=alice, reason=REASON,
        ) is None  # fmt: skip
    assert gw.budget("Call Notes").owner_user_id == fiona.id


@pytest.mark.req("SEC-15", "FR-04")
def test_removing_a_limit_needs_a_second_admin_and_adding_one_does_not(gw):
    engine, clock, rng = gw.engine, gw.clock, system_rng()
    alice, bob = actor(engine, "alice.admin"), actor(engine, "bob.admin")
    change = dict(tenant_id=alice.tenant_id, actor=alice, reason=REASON)
    soft = gw.budget("Ticket Triage")
    with engine.begin() as conn:  # soft to hard: stricter, one person
        assert approvals.change_policy(conn, clock, rng, budget_id=soft.id,
                                       budget_name="Ticket Triage", policy="HARD", **change) is None  # fmt: skip
    assert gw.budget("Ticket Triage").policy == "HARD"
    with engine.begin() as conn:  # hard to monitor: weaker, two people
        waiting = approvals.change_policy(conn, clock, rng, budget_id=soft.id,
                                          budget_name="Ticket Triage", policy="MONITOR", **change)  # fmt: skip
    assert waiting is not None and gw.budget("Ticket Triage").policy == "HARD"
    with engine.begin() as conn:
        approvals.decide(conn, clock, tenant_id=alice.tenant_id, approval_id=waiting, actor=bob,
                         approve=True)  # fmt: skip
    after = gw.budget("Ticket Triage")
    assert (after.policy, after.fail_mode) == ("MONITOR", "FAIL_OPEN")


# --- Two-person lift of a block (FR-18, SEC-07, SEC-15) -----------------------------


def ask_to_lift(gw, who, subject_type="vendor", subject_id="vendor-b"):
    with gw.engine.begin() as conn:
        return approvals.request_block_lift(
            conn, gw.clock, system_rng(), tenant_id=who.tenant_id, subject_type=subject_type,
            subject_id=subject_id, actor=who, reason=REASON,
        )  # fmt: skip


def vendor_status(gw, vendor_id="vendor-b") -> str:
    with gw.engine.connect() as conn:
        return conn.execute(select(vendors.c.status).where(vendors.c.id == vendor_id)).scalar_one()


@pytest.mark.req("SEC-07", "SEC-15", "FR-18", "B-l")
def test_lift_block_requires_second_admin(gw):
    engine, clock = gw.engine, gw.clock
    alice, bob = actor(engine, "alice.admin"), actor(engine, "bob.admin")
    approval_id = ask_to_lift(gw, alice)
    assert vendor_status(gw) == "BLOCKED"  # asking changes nothing
    assert gw.chat("Ticket Triage", "vb-large").json()["error"]["code"] == "VENDOR_BLOCKED"
    with engine.begin() as conn, pytest.raises(approvals.ApprovalError) as refused:
        approvals.decide(conn, clock, tenant_id=alice.tenant_id, approval_id=approval_id,
                         actor=alice, approve=True)  # fmt: skip
    assert refused.value.code == "SELF_APPROVAL" and vendor_status(gw) == "BLOCKED"
    with pytest.raises(approvals.ApprovalError, match="already waiting"):
        ask_to_lift(gw, bob)  # one request at a time for the same block
    with engine.begin() as conn:
        approvals.decide(conn, clock, tenant_id=alice.tenant_id, approval_id=approval_id,
                         actor=bob, approve=True)  # fmt: skip
    assert vendor_status(gw) == "ALLOWED"
    [change] = gw.rows("SELECT actor, reason FROM registry_changes ORDER BY id DESC LIMIT 1")
    assert change.actor == "alice.admin + bob.admin" and change.reason == REASON
    assert actions(engine)[-3:] == [
        "block_lift.requested", "registry.unblocked", "block_lift.approved",
    ]  # fmt: skip
    clock.advance(timedelta(seconds=5))  # the gateway's next policy snapshot
    assert gw.chat("Ticket Triage", "vb-large").status_code == 200
    with engine.begin() as conn, pytest.raises(approvals.ApprovalError, match="not waiting"):
        approvals.decide(conn, clock, tenant_id=alice.tenant_id, approval_id=approval_id,
                         actor=bob, approve=True)  # decided once  # fmt: skip


@pytest.mark.req("SEC-15")
def test_second_approver_must_differ(gw):
    """The database refuses a decision by the requester, whatever the application does."""
    alice = actor(gw.engine, "alice.admin")
    approval_id = ask_to_lift(gw, alice)
    with pytest.raises(IntegrityError, match="approvals_two_person_check"):
        gw.execute(
            "UPDATE approvals SET decision = 'APPROVED', decided_by = requested_by WHERE id = :id",
            id=approval_id,
        )
    with gw.engine.begin() as conn:  # the requester may withdraw, and only the requester
        with pytest.raises(approvals.ApprovalError, match="Only the person"):
            approvals.cancel(conn, gw.clock, tenant_id=alice.tenant_id, approval_id=approval_id,
                             actor=actor(gw.engine, "bob.admin"))  # fmt: skip
        approvals.cancel(conn, gw.clock, tenant_id=alice.tenant_id, approval_id=approval_id,
                         actor=alice)  # fmt: skip
    assert vendor_status(gw) == "BLOCKED"


@pytest.mark.req("SEC-07 (confirm within 24 hours)", "UX-11")
def test_two_person_request_expires_after_24_hours(gw):
    engine, clock = gw.engine, gw.clock
    alice, bob = actor(engine, "alice.admin"), actor(engine, "bob.admin")
    approval_id = ask_to_lift(gw, alice)
    clock.advance(timedelta(hours=24))
    with engine.begin() as conn, pytest.raises(approvals.ApprovalError) as refused:
        approvals.decide(conn, clock, tenant_id=alice.tenant_id, approval_id=approval_id,
                         actor=bob, approve=True)  # fmt: skip
    assert refused.value.code == "EXPIRED" and vendor_status(gw) == "BLOCKED"
    with engine.begin() as conn:
        assert approvals.expire_due(conn, clock, alice.tenant_id) == 1
    [row] = gw.rows("SELECT decision, decided_by FROM approvals")
    assert (row.decision, row.decided_by) == ("EXPIRED", None)
    assert actions(engine)[-1] == "block_lift.expired"
    assert ask_to_lift(gw, bob)  # a new request can be made


@pytest.mark.req("FR-18")
def test_lift_is_refused_for_something_that_is_not_blocked(gw):
    with pytest.raises(approvals.ApprovalError, match="not blocked"):
        ask_to_lift(gw, actor(gw.engine, "alice.admin"), "vendor", "vendor-a")
    with pytest.raises(approvals.ApprovalError, match="not blocked"):
        ask_to_lift(gw, actor(gw.engine, "alice.admin"), "vendor", "no-such-vendor")


# --- Held requests (FR-11, D-07, UX-D2) ----------------------------------------------


def hold(gw, content="please summarize", key=None):
    response = gw.chat("Research Agent", content=content, key=key)
    assert response.status_code == 202
    return response.headers["x-keepair-reservation-id"]


def decide_held(gw, reservation_id, who: str, approve=True):
    person = actor(gw.engine, who)
    with gw.engine.begin() as conn:
        return approvals.decide_held(
            conn, gw.clock, system_rng(), tenant_id=person.tenant_id,
            reservation_id=reservation_id, actor=person, approve=approve,
        )  # fmt: skip


def state_of(gw, reservation_id) -> str:
    [row] = gw.rows("SELECT state FROM reservations WHERE id = :id", id=reservation_id)
    return row.state


@pytest.mark.req("FR-11", "D-07", "UX-D2")
def test_approval_allows_one_matching_resubmission(gw):
    before = gw.budget("Research Agent")
    reservation = hold(gw)
    assert not gw.provider.called
    assert gw.rows("SELECT request_hash FROM reservations WHERE id = :id", id=reservation)[
        0
    ].request_hash  # a hash of the request, never its text
    decided = decide_held(gw, reservation, "alice.admin")
    assert decided.decision == "APPROVED" and state_of(gw, reservation) == "APPROVED"
    assert gw.budget("Research Agent").reserved_micros > before.reserved_micros  # still set aside
    assert not gw.provider.called  # approving sends nothing

    other = gw.chat("Research Agent", content="a different question")
    assert other.status_code == 202  # not the approved request: held on its own
    assert other.headers["x-keepair-reservation-id"] != reservation

    again = gw.chat("Research Agent", content="please summarize")  # the same request, new key
    assert again.status_code == 200 and gw.provider.call_count == 1
    assert again.headers["x-keepair-reservation-id"] == reservation
    assert state_of(gw, reservation) == "SETTLED"
    [decision] = gw.rows(
        "SELECT outcome, reason_code FROM gateway_decisions WHERE reservation_id = :id "
        "AND outcome = 'ALLOWED'", id=reservation,
    )  # fmt: skip
    assert decision.reason_code == "APPROVED_RESUBMISSION"

    third = gw.chat("Research Agent", content="please summarize")
    assert third.status_code == 202 and gw.provider.call_count == 1  # one resubmission, not two
    assert reserved_matches_open_reservations(gw)
    assert gw.budget("Research Agent").committed_micros > before.committed_micros


@pytest.mark.req("FR-11", "FR-05 (idempotency)")
def test_retry_with_the_same_idempotency_key_runs_once_approved(gw):
    reservation = hold(gw, key="retry-key-1")
    replay = gw.chat("Research Agent", content="please summarize", key="retry-key-1")
    assert replay.status_code == 202 and replay.headers["x-keepair-idempotent-replay"] == "true"
    decide_held(gw, reservation, "alice.admin")
    sent = gw.chat("Research Agent", content="please summarize", key="retry-key-1")
    assert sent.status_code == 200 and "x-keepair-idempotent-replay" not in sent.headers
    stored = gw.chat("Research Agent", content="please summarize", key="retry-key-1")
    assert stored.status_code == 200 and stored.headers["x-keepair-idempotent-replay"] == "true"
    assert gw.provider.call_count == 1


@pytest.mark.req("FR-11", "SEC-12 (caps on held count)")
def test_identical_request_while_pending_is_the_same_hold(gw):
    before = gw.budget("Research Agent").reserved_micros
    first = hold(gw)
    one_hold = gw.budget("Research Agent").reserved_micros
    assert [hold(gw) for _ in range(5)] == [first] * 5
    assert gw.budget("Research Agent").reserved_micros == one_hold > before
    assert len(gw.rows("SELECT 1 FROM reservations WHERE state = 'HELD'")) == 1


@pytest.mark.req("FR-11")
def test_rejection_releases_the_budget(gw):
    before = gw.budget("Research Agent").reserved_micros
    reservation = hold(gw)
    decide_held(gw, reservation, "bob.admin", approve=False)
    assert state_of(gw, reservation) == "RELEASED"
    assert gw.budget("Research Agent").reserved_micros == before
    assert hold(gw) != reservation  # sending it again starts a new hold
    with pytest.raises(approvals.ApprovalError, match="not waiting"):
        decide_held(gw, reservation, "bob.admin")
    assert actions(gw.engine)[-1] == "held_request.rejected"


@pytest.mark.req("FR-11 (requester cannot approve own request)", "SEC-15")
def test_owner_of_the_requesting_project_cannot_approve(gw):
    reservation = hold(gw)
    with pytest.raises(approvals.ApprovalError) as refused:
        decide_held(gw, reservation, "omar.owner")  # owns the Research Agent budget
    assert refused.value.code == "SELF_APPROVAL" and state_of(gw, reservation) == "HELD"
    with pytest.raises(approvals.ApprovalError) as refused:
        decide_held(gw, reservation, "ava.auditor")
    assert refused.value.code == "NOT_ELIGIBLE"
    # Fiona owns the Agents team budget, above the project on the limit path.
    assert decide_held(gw, reservation, "fiona.finance").decision == "APPROVED"
    [row] = gw.rows("SELECT kind, decision, decided_by_name, requested_by_name FROM approvals")
    assert tuple(row) == ("HELD_REQUEST", "APPROVED", "fiona.finance", "research-agent")


@pytest.mark.req("FR-11 (approval expiry)", "UX-D2 (within 15 minutes)", "SEC-35")
def test_unused_approval_expires_and_releases_the_budget(gw):
    before = gw.budget("Research Agent").reserved_micros
    reservation = hold(gw)
    decided = decide_held(gw, reservation, "alice.admin")
    [row] = gw.rows(
        "SELECT expires_at - now() AS left FROM reservations WHERE id = :id", id=reservation
    )
    assert timedelta(minutes=14) < row.left <= timedelta(minutes=15) and decided.resubmit_until
    gw.execute("UPDATE reservations SET expires_at = now() - interval '1 second' WHERE id = :id",
               id=reservation)  # fmt: skip
    late = gw.chat("Research Agent", content="please summarize")
    assert late.status_code == 202  # too late: it is held again, not sent
    assert late.headers["x-keepair-reservation-id"] != reservation
    with gw.engine.begin() as conn:
        swept = ledger.sweep_expired(conn, gw.clock)
    assert [(s.reservation_id, s.was_state) for s in swept] == [
        (__import__("uuid").UUID(reservation), "APPROVED")
    ]
    assert state_of(gw, reservation) == "EXPIRED"
    decide_held(gw, late.headers["x-keepair-reservation-id"], "alice.admin", approve=False)
    assert gw.budget("Research Agent").reserved_micros == before
    assert reserved_matches_open_reservations(gw)


@pytest.mark.req("FR-11", "FR-18 (a block always wins)", "Hard rule 7")
def test_approval_does_not_override_a_block(gw):
    reservation = hold(gw)
    decide_held(gw, reservation, "alice.admin")
    alice = actor(gw.engine, "alice.admin")
    with gw.engine.begin() as conn:
        add_block(conn, alice.tenant_id, "vendor", "vendor-a", "alice.admin", REASON, gw.clock)
    gw.clock.advance(timedelta(seconds=5))
    refused = gw.chat("Research Agent", content="please summarize")
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "VENDOR_BLOCKED"
    assert not gw.provider.called and state_of(gw, reservation) == "APPROVED"


# --- Kill switch (FR-22, SEC-08, UX-7) ------------------------------------------------


def switch_on(gw, scope_type="GLOBAL", scope_id="", who="alice.admin"):
    person = actor(gw.engine, who)
    with gw.engine.begin() as conn:
        return killswitch.activate(
            conn, gw.clock, system_rng(), tenant_id=person.tenant_id, scope_type=scope_type,
            scope_id=scope_id, actor=person, reason=REASON,
        )  # fmt: skip


def project_id(gw, name: str) -> str:
    return str(gw.rows("SELECT id FROM projects WHERE name = :n", n=name)[0].id)


@pytest.mark.req("SEC-08", "FR-22", "FR-18 (kill switch, propagation within 5 s)")
def test_kill_switch_denies_within_5s(gw):
    assert gw.chat("Ticket Triage").status_code == 200  # the snapshot is now cached
    switch_on(gw)
    gw.clock.advance(timedelta(seconds=5))
    for project in ("Ticket Triage", "Build Assistant", "Research Agent"):
        refused = gw.chat(project)
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "KILL_SWITCH"
    assert gw.provider.call_count == 1  # nothing was sent after the switch
    [row] = gw.rows("SELECT count(*) AS n FROM gateway_decisions WHERE reason_code = 'KILL_SWITCH'")
    assert row.n == 3  # every refusal is recorded
    assert actions(gw.engine)[-1] == "kill_switch.activated"


@pytest.mark.req("FR-22 (scopes: global, vendor, project)")
def test_kill_switch_scopes(gw):
    switch_on(gw, "PROJECT", project_id(gw, "Ticket Triage"))
    gw.clock.advance(timedelta(seconds=5))
    assert gw.chat("Ticket Triage").json()["error"]["code"] == "KILL_SWITCH"
    assert gw.chat("Reply Drafts").status_code == 200  # another project is not touched
    switch_on(gw, "VENDOR", "vendor-a")
    gw.clock.advance(timedelta(seconds=5))
    assert gw.chat("Reply Drafts").json()["error"]["code"] == "KILL_SWITCH"
    # A vendor that is not switched off keeps its own answer.
    assert gw.chat("Reply Drafts", "vb-large").json()["error"]["code"] == "VENDOR_BLOCKED"
    for bad in (("VENDOR", "no-such-vendor"), ("PROJECT", "not-a-uuid"), ("GLOBAL", "x"),
                ("TEAM", "")):  # fmt: skip
        with pytest.raises(killswitch.KillSwitchError):
            switch_on(gw, *bad)
    with pytest.raises(killswitch.KillSwitchError, match="already on"):
        switch_on(gw, "VENDOR", "vendor-a", who="bob.admin")


@pytest.mark.req("SEC-08", "SEC-06 (fail closed)", "Hard rule 7")
def test_kill_switch_holds_while_the_ledger_is_down_and_for_approved_requests(gw):
    reservation = hold(gw)
    decide_held(gw, reservation, "alice.admin")
    switch_on(gw)
    gw.clock.advance(timedelta(seconds=5))
    assert gw.chat("Research Agent", content="please summarize").json()["error"]["code"] == (
        "KILL_SWITCH"
    )
    gw.app.state.ledger_state.set_fault(True)  # monitor and soft budgets would fail open
    refused = gw.chat("Ticket Triage")
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "KILL_SWITCH"
    assert not gw.provider.called


@pytest.mark.req("SEC-08 (deactivation is two-person)", "SEC-15", "UX-7")
def test_kill_switch_off_requires_second_admin(gw):
    engine, clock = gw.engine, gw.clock
    alice, bob = actor(engine, "alice.admin"), actor(engine, "bob.admin")
    switch_id = switch_on(gw)
    with engine.begin() as conn:
        approval_id = approvals.request_kill_switch_off(
            conn, clock, system_rng(), tenant_id=alice.tenant_id, switch_id=switch_id,
            actor=alice, reason=REASON,
        )  # fmt: skip
    clock.advance(timedelta(seconds=5))
    assert gw.chat("Ticket Triage").json()["error"]["code"] == "KILL_SWITCH"  # still on
    with engine.begin() as conn, pytest.raises(approvals.ApprovalError) as refused:
        approvals.decide(conn, clock, tenant_id=alice.tenant_id, approval_id=approval_id,
                         actor=alice, approve=True)  # fmt: skip
    assert refused.value.code == "SELF_APPROVAL"
    with engine.begin() as conn:
        approvals.decide(conn, clock, tenant_id=alice.tenant_id, approval_id=approval_id,
                         actor=bob, approve=True)  # fmt: skip
    clock.advance(timedelta(seconds=5))
    assert gw.chat("Ticket Triage").status_code == 200
    [row] = gw.rows("SELECT deactivated_by_name FROM kill_switches")
    assert row.deactivated_by_name == "alice.admin + bob.admin"
    assert actions(engine)[-3:] == [
        "kill_switch_off.requested", "kill_switch.deactivated", "kill_switch_off.approved",
    ]  # fmt: skip
    assert switch_on(gw)  # it can be used again


@pytest.mark.req("UX-7 (impact preview)")
def test_kill_switch_preview_counts_what_would_stop(gw):
    gw.chat("Ticket Triage"), gw.chat("Reply Drafts"), gw.chat("Ticket Triage", "vb-large")
    tenant = tenant_of(gw.engine)
    with gw.engine.connect() as conn:
        everything = killswitch.preview(conn, tenant, "GLOBAL", "", gw.clock.now())
        vendor = killswitch.preview(conn, tenant, "VENDOR", "vendor-a", gw.clock.now())
        project = killswitch.preview(
            conn, tenant, "PROJECT", project_id(gw, "Ticket Triage"), gw.clock.now()
        )
    assert (everything.projects, everything.agents, everything.requests_5m) == (12, 12, 3)
    assert (vendor.scope_name, vendor.projects, vendor.agents, vendor.requests_5m) == (
        "Vendor vendor-a", 2, 2, 2,
    )  # fmt: skip
    assert (project.scope_name, project.projects, project.agents, project.requests_5m) == (
        "Project Ticket Triage", 1, 1, 2,
    )  # fmt: skip


@pytest.mark.req("SEC-31", "Hard rule 5")
def test_an_action_and_its_audit_record_are_one_transaction(gw):
    """If the record cannot be written, the action does not happen."""
    from keepair.audit import AuditUnavailable

    before = actions(gw.engine)
    gw.execute("DELETE FROM audit_head")
    with pytest.raises(AuditUnavailable):
        switch_on(gw)
    assert gw.rows("SELECT 1 FROM kill_switches") == []
    assert actions(gw.engine) == before
    assert budgets is not None and text is not None  # imports used by helpers above
