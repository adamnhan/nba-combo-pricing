"""Exact two-sided odds conversion and strict as-of reference validation."""
from datetime import datetime
import math


def utc_timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("An explicit timezone is required")
    return parsed.timestamp()


def remove_margin(decimal_prices, method="proportional"):
    """Return probabilities for one matched, exhaustive two-sided line.

    These are alternative assumptions about margin allocation, not observed
    true probabilities. The power exponent is solved from the quoted pair;
    it is not fitted to settlement outcomes.
    """
    if len(decimal_prices) != 2:
        raise ValueError("Exactly two sides of the same line are required")
    if any(not math.isfinite(float(p)) or float(p) <= 1 for p in decimal_prices):
        raise ValueError("Finite decimal odds above one are required")
    raw = [1/float(p) for p in decimal_prices]
    total = sum(raw)
    if not 1 <= total <= 1.35:
        raise ValueError("Unsupported two-sided overround")
    if method == "proportional":
        result = [p/total for p in raw]
    elif method == "additive":
        result = [p-(total-1)/2 for p in raw]
    elif method == "power":
        low, high = 1., 100.
        while sum(p**high for p in raw) > 1:
            high *= 2
        for _ in range(70):
            exponent = (low+high)/2
            if sum(p**exponent for p in raw) > 1:
                low = exponent
            else:
                high = exponent
        result = [p**((low+high)/2) for p in raw]
    else:
        raise ValueError("Unknown margin method")
    if any(not 0 < p < 1 for p in result):
        raise ValueError("Margin assumption gives a boundary or invalid probability")
    return tuple(result)


def validated_midpoint(*, bid, ask, observed_at, request_at, max_age_seconds=120,
                       max_spread_cents=20):
    """Validate one verified line's book; caller establishes market identity."""
    bid, ask = float(bid), float(ask)
    if not all(math.isfinite(x) for x in [bid, ask]) or not 0 <= bid <= ask <= 1:
        raise ValueError("Invalid or crossed book")
    age = utc_timestamp(request_at)-utc_timestamp(observed_at)
    if not 0 < age <= max_age_seconds:
        raise ValueError("Quote must precede the request and satisfy its age limit")
    if 100*(ask-bid) > max_spread_cents+1e-10:
        raise ValueError("Book spread exceeds the configured limit")
    midpoint = (bid+ask)/2
    if not 0 < midpoint < 1:
        raise ValueError("Boundary midpoint")
    return dict(yes=midpoint, age_seconds=age, spread_cents=100*(ask-bid))
