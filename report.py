#!/usr/bin/env python3
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
COIN_DATA_URL = "https://api.coingecko.com/api/v3/coins/bitcoin"
FNG_URL = "https://api.alternative.me/fng/?limit=1&format=json"

FNG_TRANSLATIONS = {
    "Extreme Fear": "Miedo Extremo",
    "Fear": "Miedo",
    "Neutral": "Neutral",
    "Greed": "Codicia",
    "Extreme Greed": "Codicia Extrema",
}

FNG_EMOJIS = {
    "Miedo Extremo": "😱",
    "Miedo": "😨",
    "Neutral": "😐",
    "Codicia": "🤑",
    "Codicia Extrema": "🔥",
}


def cg_headers():
    api_key = os.environ.get("COINGECKO_API_KEY")
    return {"x-cg-demo-api-key": api_key} if api_key else {}


def get_daily_prices(days=365):
    params = urllib.parse.urlencode({"vs_currency": "usd", "days": days})
    url = f"{MARKET_CHART_URL}?{params}"
    req = urllib.request.Request(url, headers=cg_headers())
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    return data["prices"]


def get_ath_atl():
    params = urllib.parse.urlencode({
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false",
        "sparkline": "false",
    })
    url = f"{COIN_DATA_URL}?{params}"
    req = urllib.request.Request(url, headers=cg_headers())
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    md = data["market_data"]
    ath = md["ath"]["usd"]
    ath_change = md["ath_change_percentage"]["usd"]
    atl = md["atl"]["usd"]
