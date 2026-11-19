"""Coverage badge state for a project (UX-2).

"Enforced" may be claimed only when the gateway is used, KeepAir holds the
provider key, and egress control is verified (FR-20). Until then gateway
traffic is "Gateway-routed" (UX-D1 default).
"""

from __future__ import annotations

from enum import StrEnum


class Coverage(StrEnum):
    ENFORCED = "Enforced"
    GATEWAY_ROUTED = "Gateway-routed"
    MONITORED = "Monitored"
    UNCONTROLLED = "Uncontrolled"


def coverage_state(key_custody: str, egress_verified: bool, uncontrolled_finding: bool) -> Coverage:
    if uncontrolled_finding:
        return Coverage.UNCONTROLLED
    if key_custody != "KEEPAIR":
        return Coverage.MONITORED
    if egress_verified:
        return Coverage.ENFORCED
    return Coverage.GATEWAY_ROUTED
