from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
import requests


class APIError(RuntimeError):
    """Raised when a Polymarket API call fails after retries."""


@dataclass
class PolymarketAPISettings:
    """Connection settings for the public Polymarket endpoints."""

    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    data_api_base_url: str = "https://data-api.polymarket.com"
    goldsky_url: Optional[str] = None
    request_timeout: float = 15.0
    max_retries: int = 3
    backoff_seconds: float = 1.5
    user_agent: str = "polymoly/1.0 (+https://github.com/polymoly)"


@dataclass
class BackfillWindow:
    """Start and end timestamps for historical downloads."""

    start: Optional[pd.Timestamp]
    end: Optional[pd.Timestamp]

    def as_epoch_seconds(self) -> Dict[str, Optional[int]]:
        start_epoch = int(self.start.timestamp()) if self.start is not None else None
        end_epoch = int(self.end.timestamp()) if self.end is not None else None
        return {"start": start_epoch, "end": end_epoch}


class PolymarketAPIClient:
    """Minimal API client wrapping the public Polymarket REST surfaces."""

    def __init__(self, settings: Optional[PolymarketAPISettings] = None) -> None:
        self.settings = settings or PolymarketAPISettings()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.settings.user_agent})

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        settings = self.settings
        last_exc: Optional[Exception] = None
        for attempt in range(1, settings.max_retries + 1):
            try:
                response = self._session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json_payload,
                    timeout=settings.request_timeout,
                )
                response.raise_for_status()
                if response.content:
                    return response.json()
                return {}
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == settings.max_retries:
                    break
                time.sleep(settings.backoff_seconds * attempt)
        raise APIError(f"Failed calling {url}") from last_exc

    @staticmethod
    def _ensure_frame(
        data: Sequence[Dict[str, Any]],
        columns: Sequence[str],
    ) -> pd.DataFrame:
        if not data:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame(data)
        for column in columns:
            if column not in frame.columns:
                frame[column] = pd.NA
        return frame[columns]

    @staticmethod
    def _normalise_timestamp(value: Any) -> pd.Timestamp:
        if value is None:
            raise ValueError("Timestamp value is missing")
        if isinstance(value, pd.Timestamp):
            ts = value
            if ts.tzinfo:
                return ts.tz_convert("UTC")
            return ts.tz_localize("UTC")
        if isinstance(value, (int, float)):
            # Support both second and millisecond epochs.
            if value > 1_000_000_000_000:
                return pd.to_datetime(int(value), unit="ms", utc=True)
            return pd.to_datetime(int(value), unit="s", utc=True)
        if isinstance(value, str):
            value = value.strip()
            if value.isdigit():
                return PolymarketAPIClient._normalise_timestamp(int(value))
            return pd.to_datetime(value, utc=True)
        raise TypeError(f"Unsupported timestamp value: {value!r}")

    # ------------------------------------------------------------------
    # Gamma endpoints
    # ------------------------------------------------------------------
    def fetch_gamma_markets(
        self,
        closed: bool = True,
        limit: int = 1000,
        include_open: bool = False,
    ) -> pd.DataFrame:
        """Download Gamma market metadata and convert it to a DataFrame."""

        params = {"closed": str(closed).lower(), "limit": limit}
        records: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        while True:
            if cursor:
                params["cursor"] = cursor
            payload = self._request(
                "GET",
                f"{self.settings.gamma_base_url}/markets",
                params=params,
            )
            entries: List[Dict[str, Any]]
            if isinstance(payload, list):
                entries = payload
                cursor = None
            else:
                entries = (
                    payload.get("data")
                    or payload.get("markets")
                    or payload.get("results")
                    or payload.get("events")
                    or []
                )
                cursor = (
                    payload.get("next")
                    or payload.get("nextCursor")
                    or payload.get("cursor")
                )
            for entry in entries:
                tokens = (
                    entry.get("clobTokenIds")
                    or entry.get("clob_tokens")
                    or []
                )
                if isinstance(tokens, dict):
                    yes_token = tokens.get("yes") or tokens.get("YES")
                    no_token = tokens.get("no") or tokens.get("NO")
                elif isinstance(tokens, list):
                    yes_token = None
                    no_token = None
                    for token_entry in tokens:
                        outcome = (
                            token_entry.get("outcome")
                            or token_entry.get("outcomeType")
                        )
                        outcome = (outcome or "").lower()
                        token_id = (
                            token_entry.get("tokenId")
                            or token_entry.get("token_id")
                            or token_entry.get("id")
                        )
                        if outcome in {"yes", "long"}:
                            yes_token = token_id
                        elif outcome in {"no", "short"}:
                            no_token = token_id
                else:
                    yes_token = None
                    no_token = None

                records.append(
                    {
                        "condition_id": entry.get("condition_id")
                        or entry.get("conditionId")
                        or entry.get("conditionID"),
                        "slug": entry.get("slug") or entry.get("question"),
                        "category": entry.get("category") or entry.get("categoryName"),
                        "end_date": entry.get("endDateIso")
                        or entry.get("endDate")
                        or entry.get("end_time"),
                        "clob_token_yes": yes_token,
                        "clob_token_no": no_token,
                        "neg_risk_group": entry.get("negRiskId")
                        or entry.get("negRiskGroup")
                        or entry.get("neg_risk_group"),
                        "status": entry.get("status"),
                        "closed": entry.get("closed"),
                        "resolved_outcome": entry.get("resolvedOutcome")
                        or entry.get("resolved_outcome"),
                    }
                )
            if not cursor or not entries:
                break
            if include_open:
                params["closed"] = "false"

        frame = pd.DataFrame.from_records(records)
        if frame.empty:
            return frame
        frame["end_date"] = frame["end_date"].apply(self._normalise_timestamp)
        frame.sort_values("end_date", inplace=True)
        frame.reset_index(drop=True, inplace=True)
        return frame

    # ------------------------------------------------------------------
    # CLOB endpoints
    # ------------------------------------------------------------------
    def fetch_clob_market_tokens(self) -> pd.DataFrame:
        """Download token/outcome metadata from the CLOB markets endpoint."""

        payload = self._request("GET", f"{self.settings.clob_base_url}/markets")
        entries: List[Dict[str, Any]]
        if isinstance(payload, list):
            entries = payload
        else:
            entries = payload.get("markets") or payload.get("data") or []
        records: List[Dict[str, Any]] = []
        for entry in entries:
            tokens = (
                entry.get("tokens")
                or entry.get("tokenPairs")
                or []
            )
            for token in tokens:
                records.append(
                    {
                        "market_id": entry.get("id") or entry.get("marketId"),
                        "condition_id": entry.get("conditionId")
                        or entry.get("condition_id")
                        or token.get("conditionId"),
                        "token_id": token.get("id")
                        or token.get("tokenId")
                        or token.get("token_id"),
                        "outcome": (
                            token.get("outcome")
                            or token.get("outcomeType")
                            or ""
                        ).lower(),
                    }
                )
        frame = pd.DataFrame.from_records(records)
        return frame

    def fetch_prices_history(
        self,
        token_id: str,
        *,
        window: Optional[BackfillWindow] = None,
        interval: str = "1h",
        fidelity: int = 1,
    ) -> pd.DataFrame:
        params: Dict[str, Any] = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        }
        if window:
            epochs = window.as_epoch_seconds()
            if epochs["start"] is not None:
                params["startTime"] = epochs["start"]
            if epochs["end"] is not None:
                params["endTime"] = epochs["end"]
        payload = self._request(
            "GET", f"{self.settings.clob_base_url}/prices-history", params=params
        )
        records: List[Dict[str, Any]] = []
        data = payload.get("history") if isinstance(payload, dict) else payload
        for point in data or []:
            ts = point.get("t") or point.get("time") or point.get("timestamp")
            price = point.get("p") or point.get("price")
            if ts is None or price is None:
                continue
            records.append(
                {
                    "token_id": token_id,
                    "timestamp": self._normalise_timestamp(ts),
                    "price": float(price),
                }
            )
        frame = pd.DataFrame.from_records(records)
        if frame.empty:
            return frame
        frame.sort_values("timestamp", inplace=True)
        frame.reset_index(drop=True, inplace=True)
        return frame

    def fetch_order_book(
        self,
        token_id: str,
        *,
        depth: int = 5,
    ) -> pd.DataFrame:
        """Fetch a single order book snapshot for the given token id."""

        params = {"token_id": token_id, "depth": depth}
        payload = self._request(
            "GET",
            f"{self.settings.clob_base_url}/book",
            params=params,
        )
        levels = payload.get("levels") or payload.get("book") or payload
        records: List[Dict[str, Any]] = []
        timestamp = payload.get("timestamp") or payload.get("ts")
        if timestamp is not None:
            ts = self._normalise_timestamp(timestamp)
        else:
            ts = pd.Timestamp.utcnow().tz_localize("UTC")
        for side_key in ("asks", "ask", "sell", "bids", "bid", "buy"):
            side_levels = levels.get(side_key) if isinstance(levels, dict) else None
            if side_levels is None:
                continue
            side = "ask" if "ask" in side_key or "sell" in side_key else "bid"
            for idx, level in enumerate(side_levels, start=1):
                price = level.get("price") or level.get("p")
                size = level.get("quantity") or level.get("size")
                if price is None or size is None:
                    continue
                records.append(
                    {
                        "token_id": token_id,
                        "timestamp": ts,
                        "side": side,
                        "level": idx,
                        "price": float(price),
                        "size": float(size),
                    }
                )
        frame = pd.DataFrame.from_records(records)
        if frame.empty:
            return frame
        frame.sort_values(["side", "level"], inplace=True)
        frame.reset_index(drop=True, inplace=True)
        return frame

    # ------------------------------------------------------------------
    # Data API endpoints
    # ------------------------------------------------------------------
    def fetch_trades(
        self,
        token_id: str,
        *,
        window: Optional[BackfillWindow] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        params: Dict[str, Any] = {
            "market": token_id,
            "limit": limit,
        }
        if window:
            epochs = window.as_epoch_seconds()
            if epochs["start"] is not None:
                params["startTime"] = epochs["start"]
            if epochs["end"] is not None:
                params["endTime"] = epochs["end"]
        trades: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            if cursor:
                params["cursor"] = cursor
            payload = self._request(
                "GET", f"{self.settings.data_api_base_url}/trades", params=params
            )
            entries = payload.get("data") if isinstance(payload, dict) else payload
            for item in entries or []:
                trade_ts = item.get("created_time")
                trade_ts = trade_ts or item.get("createdTime")
                trade_ts = trade_ts or item.get("timestamp")
                trade_ts = trade_ts or item.get("time")
                price = item.get("price") or item.get("p")
                size = item.get("size") or item.get("quantity") or item.get("q")
                taker_side = item.get("side") or item.get("takerSide")
                trade_id = (
                    item.get("id")
                    or item.get("trade_id")
                    or item.get("hash")
                )
                condition_id = (
                    item.get("condition_id")
                    or item.get("conditionId")
                    or item.get("event_id")
                )
                trades.append(
                    {
                        "trade_id": trade_id,
                        "token_id": token_id,
                        "timestamp": self._normalise_timestamp(trade_ts),
                        "price": float(price) if price is not None else pd.NA,
                        "size": float(size) if size is not None else pd.NA,
                        "taker_side": (taker_side or "").lower()
                        if taker_side
                        else pd.NA,
                        "condition_id": condition_id,
                    }
                )
            cursor = (
                payload.get("next")
                or payload.get("nextCursor")
                or payload.get("cursor")
            )
            if not cursor or not entries:
                break
        frame = pd.DataFrame.from_records(trades)
        if frame.empty:
            return frame
        frame.sort_values("timestamp", inplace=True)
        frame.reset_index(drop=True, inplace=True)
        return frame

    # ------------------------------------------------------------------
    # Goldsky subgraph
    # ------------------------------------------------------------------
    def fetch_resolutions(
        self, condition_ids: Iterable[str]
    ) -> pd.DataFrame:
        if not self.settings.goldsky_url:
            raise APIError(
                "Goldsky URL is not configured in PolymarketAPISettings"
            )
        records: List[Dict[str, Any]] = []
        query = (
            "query($ids: [String!]) {"
            "  markets(where: {conditionId_in: $ids}) {"
            "    conditionId"
            "    resolvedOutcome"
            "    resolvedTime"
            "    disputeRound"
            "  }"
            "}"
        )
        batch = list(condition_ids)
        if not batch:
            return pd.DataFrame(
                columns=[
                    "condition_id",
                    "resolved_outcome",
                    "resolve_ts",
                    "dispute_flag",
                ]
            )
        payload = self._request(
            "POST",
            self.settings.goldsky_url,
            json_payload={"query": query, "variables": {"ids": batch}},
        )
        markets = (
            payload.get("data", {})
            .get("markets", [])
        )
        for item in markets:
            ts = item.get("resolvedTime") or item.get("resolveTime")
            records.append(
                {
                    "condition_id": item.get("conditionId") or item.get("condition_id"),
                    "resolved_outcome": item.get("resolvedOutcome")
                    or item.get("resolved_outcome"),
                    "resolve_ts": self._normalise_timestamp(ts) if ts else pd.NaT,
                    "dispute_flag": (item.get("disputeRound") or 0) > 0,
                }
            )
        frame = pd.DataFrame.from_records(records)
        if frame.empty:
            return frame
        frame.sort_values("resolve_ts", inplace=True)
        frame.reset_index(drop=True, inplace=True)
        return frame
