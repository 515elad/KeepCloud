"""Money as integer micro-units plus an ISO 4217 code (hard rule 3).

No float ever touches an amount. Display formatting lives in the UI layer
(``keepair.web.formatting``), not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

MICRO_PER_UNIT = 1_000_000
BIGINT_MAX = 2**63 - 1
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Money:
    amount_micro: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.amount_micro, bool) or not isinstance(self.amount_micro, int):
            raise TypeError("amount_micro must be an int (micro-units); float is never allowed")
        if abs(self.amount_micro) > BIGINT_MAX:
            raise ValueError("amount_micro does not fit in a BIGINT")
        if not _CURRENCY_RE.match(self.currency):
            raise ValueError("currency must be a three-letter ISO 4217 code")


def micro_to_decimal(amount_micro: int) -> Decimal:
    """display_amount = amount_micro / 1,000,000 (exact decimal arithmetic)."""
    if isinstance(amount_micro, bool) or not isinstance(amount_micro, int):
        raise TypeError("amount_micro must be an int")
    return Decimal(amount_micro) / Decimal(MICRO_PER_UNIT)
