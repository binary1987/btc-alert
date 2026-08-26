#!/usr/bin/env python3
import os
import json
import math
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


def get_market_chart(days=365):
    """Devuelve (prices, volumes), ambos como listas de [timestamp_ms, valor]."""
    params = urllib.parse.urlencode({"vs_currency": "usd", "days": days})
    url = f"{MARKET_CHART_URL}?{params}"
    req = urllib.request.Request(url, headers=cg_headers())
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    return data["prices"], data["total_volumes"]


def get_ath():
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
    return ath, ath_change


def get_fear_greed():
    req = urllib.request.Request(FNG_URL)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    entry = data["data"][0]
    value = int(entry["value"])
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


def macd_cross_direction(histogram):
    if len(histogram) < 2:
        return None
    today, yesterday = histogram[-1], histogram[-2]
    color_now = "verde" if today >= 0 else "rojo"
    color_before = "verde" if yesterday >= 0 else "rojo"
    if color_now != color_before:
        return "alcista" if color_now == "verde" else "bajista"
    return None


def describe_macd(histogram):
    if len(histogram) < 2:
        return "sin datos suficientes"

    today = histogram[-1]
    yesterday = histogram[-2]

    color_now = "verde" if today >= 0 else "rojo"
    strengthening = abs(today) > abs(yesterday)
    shade = "oscuro" if strengthening else "claro"
    emoji = "🟢" if color_now == "verde" else "🔴"
    momentum_text = "impulso reforzándose" if strengthening else "impulso agotándose"

    text = f"{emoji} {color_now} {shade} ({momentum_text})"

    cross = macd_cross_direction(histogram)
    if cross:
        text += f" ⚠️ cruce {cross} hoy"

    return text


def find_extrema(values, order, min_distance):
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
        return "🔻 divergencia bajista"
    if bullish:
        return "🔺 divergencia alcista"
    return "sin divergencia clara"


def compute_bollinger(closes, period=20, num_std=2):
    """Devuelve (precio_actual, sma, banda_superior, banda_inferior) o None."""
    if len(closes) < period:
        return None

    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((p - sma) ** 2 for p in window) / period
    std_dev = math.sqrt(variance)

    upper = sma + num_std * std_dev
    lower = sma - num_std * std_dev
    current_price = closes[-1]

    return current_price, sma, upper, lower


def describe_bollinger(bollinger_data):
    if bollinger_data is None:
        return "sin datos suficientes"

    price, sma, upper, lower = bollinger_data

    if price >= upper:
        return "🔺 tocando banda superior ⚠️ posible sobrecompra"
    if price <= lower:
        return "🔻 tocando banda inferior ⚠️ posible sobreventa"
    return "dentro de las bandas (normal)"


def bollinger_signal(bollinger_data):
    if bollinger_data is None:
        return None
    price, sma, upper, lower = bollinger_data
    if price >= upper:
        return "sobrecompra"
    if price <= lower:
        return "sobreventa"
    return None


def build_alignment(rsi_daily, macd_daily_hist, div_daily, div_weekly, boll_daily_signal):
    bearish_reasons = []
    bullish_reasons = []

    if rsi_daily is not None:
        if rsi_daily >= 75:
            bearish_reasons.append("RSI diario en sobrecompra")
        elif rsi_daily <= 25:
            bullish_reasons.append("RSI diario en sobreventa")

    cross = macd_cross_direction(macd_daily_hist)
    if cross == "bajista":
        bearish_reasons.append("MACD diario cruce bajista")
    elif cross == "alcista":
        bullish_reasons.append("MACD diario cruce alcista")

    if "bajista" in div_daily:
        bearish_reasons.append("divergencia diaria bajista")
    elif "alcista" in div_daily:
        bullish_reasons.append("divergencia diaria alcista")

    if "bajista" in div_weekly:
        bearish_reasons.append("divergencia semanal bajista")
    elif "alcista" in div_weekly:
        bullish_reasons.append("divergencia semanal alcista")

    if boll_daily_signal == "sobrecompra":
        bearish_reasons.append("Bollinger diario en sobrecompra")
    elif boll_daily_signal == "sobreventa":
        bullish_reasons.append("Bollinger diario en sobreventa")

    if len(bearish_reasons) >= 2:
        return f"🎯 Alineación bajista: {', '.join(bearish_reasons)} → posible giro bajista"
    if len(bullish_reasons) >= 2:
        return f"🎯 Alineación alcista: {', '.join(bullish_reasons)} → posible giro alcista"
    return None


def trend_label(bullish_count, bearish_count):
    if bullish_count > bearish_count:
        return "📈 Alcista"
    if bearish_count > bullish_count:
        return "📉 Bajista"
    return "➖ Lateral / mixta"


def compute_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def compute_roc(closes, period):
    """Tasa de cambio (%) entre el precio actual y el de hace 'period' velas."""
    if len(closes) <= period:
        return None
    past = closes[-period - 1]
    current = closes[-1]
    if past == 0:
        return None
    return ((current - past) / past) * 100


def compute_volume_confirmation(daily_closes, daily_volumes, avg_period=30):
    """
    Compara el volumen de hoy contra la media de los últimos N días.
    Si el precio subió con volumen alto -> confirmación alcista.
    Si el precio bajó con volumen alto -> confirmación bajista.
    """
    if len(daily_volumes) < avg_period + 1 or len(daily_closes) < 2:
        return None

    avg_volume = sum(daily_volumes[-avg_period - 1:-1]) / avg_period
    today_volume = daily_volumes[-1]

    if avg_volume == 0:
        return None

    relative_volume = today_volume / avg_volume
    price_change = daily_closes[-1] - daily_closes[-2]

    if relative_volume < 1.2:
        return None

    if price_change > 0:
        return "alcista"
    if price_change < 0:
        return "bajista"
    return None


def compute_trend_summary(rsi_daily, rsi_weekly, rsi_monthly, macd_daily_hist,
                           macd_weekly_hist, boll_daily, boll_weekly, fng_value,
                           daily_closes, daily_volumes):
    corto_bull, corto_bear = 0, 0
    if macd_daily_hist:
        if macd_daily_hist[-1] >= 0:
            corto_bull += 1
        else:
            corto_bear += 1
    if rsi_daily is not None:
        if rsi_daily > 50:
            corto_bull += 1
        else:
            corto_bear += 1
    if boll_daily is not None:
        price, sma, upper, lower = boll_daily
        if price > sma:
            corto_bull += 1
        else:
            corto_bear += 1

    roc_7 = compute_roc(daily_closes, 7)
    if roc_7 is not None:
        if roc_7 > 0:
            corto_bull += 1
        else:
            corto_bear += 1

    vol_confirm = compute_volume_confirmation(daily_closes, daily_volumes)
    if vol_confirm == "alcista":
        corto_bull += 1
    elif vol_confirm == "bajista":
        corto_bear += 1

    medio_bull, medio_bear = 0, 0
    if macd_weekly_hist:
        if macd_weekly_hist[-1] >= 0:
            medio_bull += 1
        else:
            medio_bear += 1
    if rsi_weekly is not None:
        if rsi_weekly > 50:
            medio_bull += 1
        else:
            medio_bear += 1
    if boll_weekly is not None:
        price, sma, upper, lower = boll_weekly
        if price > sma:
            medio_bull += 1
        else:
            medio_bear += 1

    roc_30 = compute_roc(daily_closes, 30)
    if roc_30 is not None:
        if roc_30 > 0:
            medio_bull += 1
        else:
            medio_bear += 1

    largo_bull, largo_bear = 0, 0
    if rsi_monthly is not None:
        if rsi_monthly > 50:
            largo_bull += 1
        else:
            largo_bear += 1
    if fng_value is not None:
        if fng_value > 50:
            largo_bull += 1
        else:
            largo_bear += 1

    sma50 = compute_sma(daily_closes, 50)
    sma200 = compute_sma(daily_closes, 200)
    if sma50 is not None and sma200 is not None:
        if sma50 > sma200:
            largo_bull += 1
        else:
            largo_bear += 1

    roc_90 = compute_roc(daily_closes, 90)
    if roc_90 is not None:
        if roc_90 > 0:
            largo_bull += 1
        else:
            largo_bear += 1

    return (
        trend_label(corto_bull, corto_bear),
        trend_label(medio_bull, medio_bear),
        trend_label(largo_bull, largo_bear),
    )


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


def main():
    prices, volumes = get_market_chart(days=365)

    daily_closes = [p for _, p in prices]
    daily_volumes = [v for _, v in volumes]
    weekly_closes = group_last(prices, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))
    monthly_closes = group_last(prices, lambda dt: (dt.year, dt.month))

    rsi_daily = compute_rsi(daily_closes)
    rsi_weekly = compute_rsi(weekly_closes)
    rsi_monthly = compute_rsi(monthly_closes)

    macd_daily_hist = compute_macd_histogram(daily_closes)
    macd_weekly_hist = compute_macd_histogram(weekly_closes)

    div_daily = detect_divergence(daily_closes, order=3, min_distance=5)
    div_weekly = detect_divergence(weekly_closes, order=2, min_distance=3)

    boll_daily = compute_bollinger(daily_closes)
    boll_weekly = compute_bollinger(weekly_closes)
    boll_daily_signal = bollinger_signal(boll_daily)

    fng_value, fng_text = get_fear_greed()
    fng_emoji = FNG_EMOJIS.get(fng_text, "")

    ath, ath_change = get_ath()

    current_price = daily_closes[-1]
    atl_12m = min(daily_closes)
    atl_12m_change = ((current_price - atl_12m) / atl_12m) * 100

    alignment = build_alignment(rsi_daily, macd_daily_hist, div_daily, div_weekly, boll_daily_signal)

    corto, medio, largo = compute_trend_summary(
        rsi_daily, rsi_weekly, rsi_monthly,
        macd_daily_hist, macd_weekly_hist,
        boll_daily, boll_weekly, fng_value,
        daily_closes, daily_volumes,
    )

    lines = [
        "📊 Informe diario BTC",
        "----------------------------------",
        f"Fear & Greed: {fng_emoji} {fng_text} ({fng_value})",
        f"RSI diario: {rsi_daily:.0f}{zone_flag(rsi_daily)}",
        f"RSI semanal: {rsi_weekly:.0f}{zone_flag(rsi_weekly)}",
        f"RSI mensual: {rsi_monthly:.0f}{zone_flag(rsi_monthly)}",
        "----------------------------------",
        f"MACD diario: {describe_macd(macd_daily_hist)}",
        f"MACD semanal: {describe_macd(macd_weekly_hist)}",
        "----------------------------------",
        f"Divergencia diaria: {div_daily}",
        f"Divergencia semanal: {div_weekly}",
        "----------------------------------",
        f"Bollinger diario: {describe_bollinger(boll_daily)}",
        f"Bollinger semanal: {describe_bollinger(boll_weekly)}",
        "----------------------------------",
        f"ATH: {ath:,.0f} $ ({ath_change:.1f}%)",
        f"ATL: {atl_12m:,.0f} $ ({atl_12m_change:+.1f}%) (mínimo últimos 12 meses)",
        "----------------------------------",
        f"Tendencia corto plazo: {corto}",
        f"Tendencia medio plazo: {medio}",
        f"Tendencia largo plazo: {largo}",
    ]

    if alignment:
        lines.append("----------------------------------")
        lines.append(alignment)

    msg = "\n".join(lines)

    print(msg)
    send_telegram(msg)


if __name__ == "__main__":
    main()
