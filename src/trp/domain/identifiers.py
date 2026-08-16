"""Internal and external identifier types.

Internal identifiers (`SecurityId`, `EntityId`) are immutable, opaque, and never reused —
they are the spine of the security master. External identifiers (ISIN, SEDOL, ticker, …)
are time-varying facts *about* a security, modelled in the identifier map (QNT-007), and
must never be used as permanent keys.
"""

import uuid
from enum import StrEnum
from typing import NewType

SecurityId = NewType("SecurityId", str)
EntityId = NewType("EntityId", str)


def new_security_id() -> SecurityId:
    return SecurityId(f"SEC-{uuid.uuid4()}")


def new_entity_id() -> EntityId:
    return EntityId(f"ENT-{uuid.uuid4()}")


class IdentifierKind(StrEnum):
    """Kinds of external identifier that may map to a security over an effective range."""

    ISIN = "isin"
    SEDOL = "sedol"
    CUSIP = "cusip"
    TICKER = "ticker"  # only meaningful together with an exchange (MIC)
    FIGI = "figi"
    PROVIDER = "provider"  # provider-native identifier, qualified by provider name
