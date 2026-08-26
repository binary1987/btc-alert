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


def compute_rsi_series(closes, period=14):
    """Devuelve la lista de RSI a lo largo del tiempo (no solo el valor final)."""
    if len(closes) < period + 2:
        return []

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def rsi_value(ag, al):
        if al == 0:
            return 100.0
        rs = ag / al
        return 100 - (100 / (1 + rs))

    rsis = [rsi_value(avg_gain, avg_loss)]
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsis.append(rsi_value(avg_gain, avg_loss))

    return rsis


def zone_flag(rsi):
    if rsi is None:
        return ""
    if rsi >= 75:
        return " ⚠️ sobrecompra"
    if rsi <= 25:
        return " ⚠️ sobreventa"
    return ""


def ema_series(closes, period):
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(closes[:period]) / period]
    for price in closes[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


def compute_macd_histogram(closes):
    if len(closes) < 35:
        return []

    ema12_full = ema_series(closes, 12)
    ema26_full = ema_series(closes, 26)

    offset = len(ema12_full) - len(ema26_full)
    ema12_aligned = ema12_full[offset:]

    macd_line = [a - b for a, b in zip(ema12_aligned, ema26_full)]

    signal_line = ema_series(macd_line, 9)
    macd_aligned = macd_line[len(macd_line) - len(signal_line):]

    histogram = [m - s for m, s in zip(macd_aligned, signal_line)]
    return histogram


def describe_macd(histogram):
    if len(histogram) < 2:
        return "sin datos suficientes"

    today = histogram[-1]
    yesterday = histogram[-2]

    color_now = "verde" if today >= 0 else "rojo"
    color_before = "verde" if yesterday >= 0 else "rojo"

    strengthening = abs(today) > abs(yesterday)
    shade = "oscuro" if strengthening else "claro"
    emoji = "🟢" if color_now == "verde" else "🔴"
    momentum_text = "impulso reforzándose" if strengthening else "impulso agotándose"

    text = f"{emoji} {color_now} {shade} ({momentum_text})"

    if color_now != color_before:
        cruce = "cruce alcista hoy" if color_now == "verde" else "cruce bajista hoy"
        text += f" ⚠️ {cruce}"

    return text


def find_extrema(values, order, min_distance):
    """Encuentra picos y valles locales con una separación mínima entre ellos."""
    peaks = []
    troughs = []
    n = len(values)
    i = order
    while i < n - order:
        window_before = values[max(0, i - order):i]
        window_after = values[i + 1:i + 1 + order]

        if window_before and window_after:
            is_peak = all(values[i] >= v for v in window_before) and all(values[i] >= v for v in window_after)
            is_trough = all(values[i] <= v for v in window_before) and all(values[i] <= v for v in window_after)

            if is_peak:
                peaks.append(i)
                i += min_distance
                continue
            if is_trough:
                troughs.append(i)
                i += min_distance
                continue
        i += 1

    return peaks, troughs


def detect_divergence(closes, order=3, min_distance=5, rsi_period=14):
    """
    Compara los dos últimos picos y los dos últimos valles de precio vs RSI.
    Devuelve un texto describiendo la divergencia encontrada (o su ausencia).
    """
    rsi_series = compute_rsi_series(closes, period=rsi_period)
    if len(rsi_series) < order * 2 + min_distance + 2:
        return "sin datos suficientes"

    aligned_closes = closes[-len(rsi_series):]

    peaks, troughs = find_extrema(aligned_closes, order, min_distance)

    bearish = False
    if len(peaks) >= 2:
        i1, i2 = peaks[-2], peaks[-1]
        if aligned_closes[i2] > aligned_closes[i1] and rsi_series[i2] < rsi_series[i1]:
            bearish = True

    bullish = False
    if len(troughs) >= 2:
        i1, i2 = troughs[-2], troughs[-1]
        if aligned_closes[i2] < aligned_closes[i1] and rsi_series[i2] > rsi_series[i1]:
            bullish = True

    if bearish and bullish:
        return "⚠️ señales mixtas (revisar gráfico)"
    if bearish:
        return "🔻 divergencia bajista (precio sube, RSI pierde fuerza)"
    if bullish:
        return "🔺 divergencia alcista (precio baja, RSI gana fuerza)"
    return "sin divergencia clara"


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

    macd_daily_hist = compute_macd_histogram(daily_closes)
    macd_weekly_hist = compute_macd_histogram(weekly_closes)

    div_daily = detect_divergence(daily_closes, order=3, min_distance=5)
    div_weekly = detect_divergence(weekly_closes, order=2, min_distance=3)

    fng_value, fng_text = get_fear_greed()
    fng_emoji = FNG_EMOJIS.get(fng_text, "")

    msg = (
        "📊 Informe diario BTC\n"
        "----------------------------------\n"
        f"Fear & Greed: {fng_emoji} {fng_text} ({fng_value})\n"
        f"RSI diario: {rsi_daily:.0f}{zone_flag(rsi_daily)}\n"
        f"RSI semanal: {rsi_weekly:.0f}{zone_flag(rsi_weekly)}\n"
        f"RSI mensual: {rsi_monthly:.0f}{zone_flag(rsi_monthly)}\n"
        "----------------------------------\n"
        f"MACD diario: {describe_macd(macd_daily_hist)}\n"
        f"MACD semanal: {describe_macd(macd_weekly_hist)}\n"
        "----------------------------------\n"
        f"Divergencia diaria: {div_daily}\n"
        f"Divergencia semanal: {div_weekly}"
    )

    print(msg)
    send_telegram(msg)


if __name__ == "__main__":
    main()
