from __future__ import annotations

import pandas as pd

from a_stock_radar.features import consecutive_sign_days, rolling_percentile


def test_rolling_percentile_requires_minimum_samples() -> None:
    assert rolling_percentile(pd.Series([1, 2, 3]), minimum=4) is None
    assert rolling_percentile(pd.Series(range(1, 101)), minimum=60) == 100.0


def test_consecutive_sign_days() -> None:
    values = pd.Series([-1, 0.2, 0.3, 0.4])
    assert consecutive_sign_days(values, positive=True) == 3
    assert consecutive_sign_days(values, positive=False) == 0
