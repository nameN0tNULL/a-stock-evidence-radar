from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


def rolling_percentile(values: pd.Series, window: int = 250, minimum: int = 60) -> float | None:
    series = pd.to_numeric(values, errors="coerce").dropna().tail(window)
    if len(series) < minimum:
        return None
    current = series.iloc[-1]
    return float((series <= current).mean() * 100)


def consecutive_sign_days(values: pd.Series, positive: bool = True, max_days: int = 20) -> int:
    count = 0
    for value in reversed(pd.to_numeric(values, errors="coerce").dropna().tail(max_days).tolist()):
        condition = value > 0 if positive else value < 0
        if not condition:
            break
        count += 1
    return count


def summarize_market(frame: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    pct = pd.to_numeric(frame["pct_change"], errors="coerce").dropna()
    amount = pd.to_numeric(frame.get("amount"), errors="coerce").fillna(0)
    caps = pd.to_numeric(frame.get("float_market_cap"), errors="coerce")
    valid_caps = caps.notna() & (caps > 0) & pd.to_numeric(frame["pct_change"], errors="coerce").notna()
    cap_weighted = (
        float(np.average(frame.loc[valid_caps, "pct_change"], weights=caps[valid_caps]))
        if valid_caps.any()
        else None
    )
    return pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "total_amount": float(amount.sum()),
                "advancers": int((pct > 0).sum()),
                "decliners": int((pct < 0).sum()),
                "unchanged": int((pct == 0).sum()),
                "breadth_ratio": float((pct > 0).mean()) if len(pct) else np.nan,
                "median_return": float(pct.median()) if len(pct) else np.nan,
                "cap_weighted_return": cap_weighted,
                "limit_up_count": int((pct >= 9.5).sum()),
                "limit_down_count": int((pct <= -9.5).sum()),
            }
        ]
    )


def build_market_features(
    history: pd.DataFrame,
    trade_date: date,
    window: int,
    minimum: int,
) -> dict[str, Any]:
    if history.empty:
        return {"available": False}
    data = history.copy().sort_values("trade_date")
    data = data[data["trade_date"] <= trade_date]
    current = data[data["trade_date"] == trade_date]
    if current.empty:
        return {"available": False}
    row = current.iloc[-1]
    amount = pd.to_numeric(data["total_amount"], errors="coerce")
    breadth = pd.to_numeric(data["breadth_ratio"], errors="coerce")
    amount_5d_change = None
    if len(data) >= 6 and amount.iloc[-6] != 0:
        amount_5d_change = float(amount.iloc[-1] / amount.iloc[-6] - 1)
    return {
        "available": True,
        "total_amount": float(row["total_amount"]),
        "advancers": int(row["advancers"]),
        "decliners": int(row["decliners"]),
        "unchanged": int(row["unchanged"]),
        "breadth_ratio": float(row["breadth_ratio"]),
        "median_return": float(row["median_return"]),
        "cap_weighted_return": None
        if pd.isna(row.get("cap_weighted_return"))
        else float(row["cap_weighted_return"]),
        "limit_up_count": int(row["limit_up_count"]),
        "limit_down_count": int(row["limit_down_count"]),
        "amount_5d_change": amount_5d_change,
        "amount_percentile": rolling_percentile(amount, window, minimum),
        "breadth_percentile": rolling_percentile(breadth, window, minimum),
    }


def enrich_etf_history(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return history
    data = history.copy().sort_values(["fund_code", "trade_date"])
    for column in ["total_shares", "nav", "price", "amount"]:
        data[column] = pd.to_numeric(data.get(column), errors="coerce")
    data["previous_shares"] = data.groupby("fund_code")["total_shares"].shift(1)
    data["share_delta"] = data["total_shares"] - data["previous_shares"]
    data["estimated_creation_flow"] = data["share_delta"] * data["nav"]
    data["previous_assets_proxy"] = data["previous_shares"] * data["nav"]
    data["flow_ratio"] = data["estimated_creation_flow"] / data["previous_assets_proxy"].replace(0, np.nan)
    data["price_return"] = data.groupby("fund_code")["price"].pct_change(fill_method=None)
    data["turnover_to_assets"] = data["amount"] / (data["total_shares"] * data["nav"]).replace(0, np.nan)
    return data


def build_etf_theme_features(
    history: pd.DataFrame,
    trade_date: date,
    window: int,
    minimum: int,
) -> dict[str, dict[str, Any]]:
    data = enrich_etf_history(history)
    if data.empty:
        return {}
    daily = (
        data.groupby(["trade_date", "theme_id", "theme_name"], dropna=False)
        .agg(
            estimated_flow=("estimated_creation_flow", "sum"),
            previous_assets=("previous_assets_proxy", "sum"),
            amount=("amount", "sum"),
            assets_proxy=("total_shares", lambda x: float(x.sum())),
            valid_funds=("share_delta", lambda x: int(x.notna().sum())),
            positive_funds=("share_delta", lambda x: int((x > 0).sum())),
            negative_funds=("share_delta", lambda x: int((x < 0).sum())),
            price_positive_funds=("price_return", lambda x: int((x > 0).sum())),
            valid_price_funds=("price_return", lambda x: int(x.notna().sum())),
            mean_price_return=("price_return", "mean"),
            turnover_to_assets=("turnover_to_assets", "mean"),
            official_share_coverage=("share_is_official", lambda x: float(pd.Series(x).fillna(False).mean())),
        )
        .reset_index()
    )
    daily["flow_ratio"] = daily["estimated_flow"] / daily["previous_assets"].replace(0, np.nan)
    daily["positive_coverage"] = daily["positive_funds"] / daily["valid_funds"].replace(0, np.nan)
    daily["negative_coverage"] = daily["negative_funds"] / daily["valid_funds"].replace(0, np.nan)
    daily["price_breadth"] = daily["price_positive_funds"] / daily["valid_price_funds"].replace(0, np.nan)
    results: dict[str, dict[str, Any]] = {}
    for theme_id, group in daily.groupby("theme_id"):
        group = group.sort_values("trade_date")
        group = group[group["trade_date"] <= trade_date]
        current = group[group["trade_date"] == trade_date]
        if current.empty:
            continue
        row = current.iloc[-1]
        last5 = group.tail(5)
        last20 = group.tail(20)
        flow_5d = float(last5["estimated_flow"].sum(min_count=1))
        assets_5d = float(last5["previous_assets"].iloc[0]) if len(last5) else np.nan
        flow_ratio_5d = flow_5d / assets_5d if assets_5d and not np.isnan(assets_5d) else None
        flow_20d = float(last20["estimated_flow"].sum(min_count=1))
        assets_20d = float(last20["previous_assets"].iloc[0]) if len(last20) else np.nan
        flow_ratio_20d = flow_20d / assets_20d if assets_20d and not np.isnan(assets_20d) else None
        results[str(theme_id)] = {
            "theme_id": str(theme_id),
            "theme_name": str(row["theme_name"]),
            "estimated_flow_1d": None if pd.isna(row["estimated_flow"]) else float(row["estimated_flow"]),
            "estimated_flow_5d": flow_5d,
            "estimated_flow_20d": flow_20d,
            "flow_ratio_1d": None if pd.isna(row["flow_ratio"]) else float(row["flow_ratio"]),
            "flow_ratio_5d": flow_ratio_5d,
            "flow_ratio_20d": flow_ratio_20d,
            "flow_percentile": rolling_percentile(group["flow_ratio"], window, minimum),
            "positive_coverage": None if pd.isna(row["positive_coverage"]) else float(row["positive_coverage"]),
            "negative_coverage": None if pd.isna(row["negative_coverage"]) else float(row["negative_coverage"]),
            "price_breadth": None if pd.isna(row["price_breadth"]) else float(row["price_breadth"]),
            "mean_price_return": None if pd.isna(row["mean_price_return"]) else float(row["mean_price_return"]),
            "turnover_percentile": rolling_percentile(group["turnover_to_assets"], window, minimum),
            "positive_persistence_days": consecutive_sign_days(group["flow_ratio"], True),
            "negative_persistence_days": consecutive_sign_days(group["flow_ratio"], False),
            "valid_funds": int(row["valid_funds"]),
            "official_share_coverage": float(row["official_share_coverage"]),
            "history_samples": int(group["flow_ratio"].notna().sum()),
        }
    return results


def enrich_margin_history(history: pd.DataFrame, group_column: str) -> pd.DataFrame:
    if history.empty:
        return history
    data = history.copy().sort_values([group_column, "trade_date"])
    data["financing_balance"] = pd.to_numeric(data["financing_balance"], errors="coerce")
    data["previous_financing_balance"] = data.groupby(group_column)["financing_balance"].shift(1)
    data["financing_change"] = data["financing_balance"] - data["previous_financing_balance"]
    data["financing_change_ratio"] = data["financing_change"] / data["previous_financing_balance"].replace(0, np.nan)
    return data


def build_margin_market_features(
    history: pd.DataFrame,
    trade_date: date,
    window: int,
    minimum: int,
) -> dict[str, Any]:
    if history.empty:
        return {"available": False}
    daily = (
        history.groupby("trade_date", as_index=False)
        .agg(financing_balance=("financing_balance", "sum"), financing_buy=("financing_buy", "sum"))
        .sort_values("trade_date")
    )
    daily["previous_balance"] = daily["financing_balance"].shift(1)
    daily["change"] = daily["financing_balance"] - daily["previous_balance"]
    daily["change_ratio"] = daily["change"] / daily["previous_balance"].replace(0, np.nan)
    current = daily[daily["trade_date"] == trade_date]
    if current.empty:
        return {"available": False}
    row = current.iloc[-1]
    balance_5d = None
    balance_20d = None
    if len(daily) >= 6:
        balance_5d = float(row["financing_balance"] / daily.iloc[-6]["financing_balance"] - 1)
    if len(daily) >= 21:
        balance_20d = float(row["financing_balance"] / daily.iloc[-21]["financing_balance"] - 1)
    return {
        "available": True,
        "financing_balance": float(row["financing_balance"]),
        "financing_buy": float(row["financing_buy"]),
        "change_1d": None if pd.isna(row["change"]) else float(row["change"]),
        "change_ratio_1d": None if pd.isna(row["change_ratio"]) else float(row["change_ratio"]),
        "change_ratio_5d": balance_5d,
        "change_ratio_20d": balance_20d,
        "change_percentile": rolling_percentile(daily["change_ratio"], window, minimum),
        "positive_persistence_days": consecutive_sign_days(daily["change_ratio"], True),
        "negative_persistence_days": consecutive_sign_days(daily["change_ratio"], False),
        "history_samples": int(daily["change_ratio"].notna().sum()),
    }


def build_margin_theme_features(
    history: pd.DataFrame,
    trade_date: date,
    window: int,
    minimum: int,
) -> dict[str, dict[str, Any]]:
    if history.empty or "theme_id" not in history:
        return {}
    mapped = history.dropna(subset=["theme_id"]).copy()
    if mapped.empty:
        return {}
    daily = (
        mapped.groupby(["trade_date", "theme_id", "theme_name"], as_index=False)
        .agg(
            financing_balance=("financing_balance", "sum"),
            financing_buy=("financing_buy", "sum"),
            mapped_securities=("security_code", "nunique"),
        )
        .sort_values(["theme_id", "trade_date"])
    )
    daily["previous_balance"] = daily.groupby("theme_id")["financing_balance"].shift(1)
    daily["change"] = daily["financing_balance"] - daily["previous_balance"]
    daily["change_ratio"] = daily["change"] / daily["previous_balance"].replace(0, np.nan)
    results: dict[str, dict[str, Any]] = {}
    for theme_id, group in daily.groupby("theme_id"):
        group = group[group["trade_date"] <= trade_date].sort_values("trade_date")
        current = group[group["trade_date"] == trade_date]
        if current.empty:
            continue
        row = current.iloc[-1]
        change_5d = None
        change_20d = None
        if len(group) >= 6:
            change_5d = float(row["financing_balance"] / group.iloc[-6]["financing_balance"] - 1)
        if len(group) >= 21:
            change_20d = float(row["financing_balance"] / group.iloc[-21]["financing_balance"] - 1)
        results[str(theme_id)] = {
            "theme_id": str(theme_id),
            "theme_name": str(row["theme_name"]),
            "financing_balance": float(row["financing_balance"]),
            "change_1d": None if pd.isna(row["change"]) else float(row["change"]),
            "change_ratio_1d": None if pd.isna(row["change_ratio"]) else float(row["change_ratio"]),
            "change_ratio_5d": change_5d,
            "change_ratio_20d": change_20d,
            "change_percentile": rolling_percentile(group["change_ratio"], window, minimum),
            "positive_persistence_days": consecutive_sign_days(group["change_ratio"], True),
            "negative_persistence_days": consecutive_sign_days(group["change_ratio"], False),
            "mapped_securities": int(row["mapped_securities"]),
            "history_samples": int(group["change_ratio"].notna().sum()),
        }
    return results
