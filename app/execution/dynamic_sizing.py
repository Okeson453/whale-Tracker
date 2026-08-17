"""Dynamic position sizing.

Sizes a trade based on the triggering wallet's live scorecard (see
analytics/wallet_performance.py) rather than a single flat cap for every
wallet. A proven high-pass-rate wallet gets sized toward the configured
maximum; an unproven or low-pass-rate wallet gets sized toward the
configured minimum. This runs independently of, and does not replace,
the guardrails position cap check.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.analytics.analytics_models import WalletScorecardDataclass
from app.config import yaml_settings

logger = logging.getLogger(__name__)


def _thresholds() -> dict[str, Any]:
    return yaml_settings.dynamic_sizing


def calculate_position_size(
    scorecard: WalletScorecardDataclass | None,
) -> Decimal:
    """Return the USD position size for a trade triggered by *scorecard*'s wallet.

    - No scorecard (unproven wallet, never scored) → configured minimum.
    - Pass rate at or above the configured ceiling → configured maximum.
    - In between → linear interpolation between min and max.
    """
    thresholds = _thresholds()
    min_usd = Decimal(str(thresholds.get("min_position_usd", 50)))
    max_usd = Decimal(str(thresholds.get("max_position_usd", 500)))
    ceiling_pct = Decimal(str(thresholds.get("min_pass_rate_pct_for_max", 80)))

    if scorecard is None or scorecard.total_alerts == 0:
        logger.debug("No scorecard available — sizing at minimum (%s)", min_usd)
        return min_usd

    pass_rate = Decimal(str(scorecard.pass_rate))
    if pass_rate <= 0:
        return min_usd
    if pass_rate >= ceiling_pct:
        return max_usd

    # Linear interpolation between min and max based on pass_rate / ceiling
    fraction = pass_rate / ceiling_pct
    size = min_usd + (max_usd - min_usd) * fraction
    size = size.quantize(Decimal("0.01"))

    logger.info(
        "Dynamic size for wallet %s: pass_rate=%.1f%% -> $%s",
        scorecard.wallet_id,
        float(pass_rate),
        size,
    )
    return size
