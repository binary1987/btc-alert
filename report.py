#!/usr/bin/env python3
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
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


def get_daily_prices(days=365):
    api_key = os.environ.get("COINGECKO_API_KEY")
    headers = {"x-cg-demo-api-key": api_key} if api_key else {}
    params = urllib.parse.urlencode({"vs_currency": "usd", "days": days})
    url = f"{COINGECKO_URL}?{params}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    return data["prices"]


def get_fear_greed():
    req = urllib.request.Request(FNG_URL)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    entry = data["data"][0]
    value = entry["value"]
    classification = entry["value_classification"]
    return value, FNG_TRANSLATIONS.get(classification, classification)


def group_last(prices, keyfunc):
    groups = {}
    order = []
    for ts, price in prices:
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        key = keyfunc(dt)
        if key not in groups:
            order.append(key)
        groups[key] = price
    return [groups[k] for k in order]


def compute_rsi(closes, period=14):
    if len(closes) < 3:
        return None
    period = min(period, len(closes) - 1)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def zone_flag(rsi):
    if rsi is None:
        return ""
    if rsi >= 75:
        return " ⚠️ sobrecompra"
    if rsi <= 25:
        return " ⚠️ sobreventa"
    return ""


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


def main():
    prices = get_daily_prices(days=365)

    daily_closes = [p for _, p in prices]
    weekly_closes = group_last(prices, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))
    monthly_closes = group_last(prices, lambda dt: (dt.year, dt.month))

    rsi_daily = compute_rsi(daily_closes)
    rsi_weekly = compute_rsi(weekly_closes)
    rsi_monthly = compute_rsi(monthly_closes)

    fng_value, fng_text = get_fear_greed()
    fng_emoji = FNG_EMOJIS.get(fng_text, "")

    msg = (
        "📊 Informe diario BTC\n"
        "-----------------------------------\n"
        f"Fear & Greed: {fng_emoji} {fng_text} ({fng_value})\n"
        f"RSI diario: {rsi_daily:.0f}{zone_flag(rsi_daily)}\n"
        f"RSI semanal: {rsi_weekly:.0f}{zone_flag(rsi_weekly)}\n"
        f"RSI mensual: {rsi_monthly:.0f}{zone_flag(rsi_monthly)}"
    )

    print(msg)
    send_telegram(msg)


if __name__ == "__main__":
    main()
