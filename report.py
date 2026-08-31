#!/usr/bin/env python3
# report.py
import os
import json
import math
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
MARKET_CHART_RANGE_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
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

LAST_REPORT_TIER_FILE = "last_report_tier.txt"


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


def get_price_range(from_ts, to_ts):
    """
    Devuelve la lista de precios [timestamp_ms, precio] entre dos timestamps
    (segundos, UTC). Se usa para calcular el ATL real desde el último ATH,
    sin la limitación de la ventana rodante de 365 dias.
    """
    params = urllib.parse.urlencode({"vs_currency": "usd", "from": from_ts, "to": to_ts})
    url = f"{MARKET_CHART_RANGE_URL}?{params}"
    req = urllib.request.Request(url, headers=cg_headers())
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    return data["prices"]


def get_btc_weekly_closes_twelvedata(outputsize=260, retries=3, retry_delay=10):
    """
    Historico semanal de BTC/USD via Twelve Data, necesario para la SMA200
    semanal: CoinGecko en el plan gratuito solo da 365 dias (~52 semanas),
    muy por debajo de las 200 semanas que hacen falta. Twelve Data si
    permite pedir varios años de golpe. Devuelve una lista de closes en
    orden cronologico (ascendente).
    """
    api_key = os.environ.get("TWELVEDATA_API_KEY")
    params = urllib.parse.urlencode({
        "symbol": "BTC/USD",
        "interval": "1week",
        "outputsize": outputsize,
        "order": "ASC",
        "apikey": api_key,
    })
    url = f"https://api.twelvedata.com/time_series?{params}"

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
            if "values" not in data:
                raise ValueError(f"respuesta sin 'values': {data}")
            return [float(v["close"]) for v in data["values"]]
        except Exception as e:
            last_error = e
            print(f"Aviso: fallo al pedir BTC/USD semanal de Twelve Data (intento {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(retry_delay)

    print(f"Aviso: no se pudo obtener el historico semanal de Twelve Data tras {retries} intentos ({last_error})")
    return []


def get_sma200_weekly_data(current_price):
    """
    Calcula la distancia % del precio actual a la SMA200 semanal, y su
    divergencia, usando el historico semanal de Twelve Data. Si algo falla
    (sin key, sin datos suficientes, error de red), devuelve (None, "sin
    datos suficientes") para que esa condicion simplemente no puntue, sin
    romper el resto del sistema.
    """
    weekly_closes_td = get_btc_weekly_closes_twelvedata(outputsize=260)
    if len(weekly_closes_td) < 200:
        return None, "sin datos suficientes"

    sma200w = compute_sma(weekly_closes_td, 200)
    sma200w_pct = None
    if sma200w:
        sma200w_pct = ((current_price - sma200w) / sma200w) * 100

    div_sma200w = detect_sma_divergence(weekly_closes_td, period=200, order=2, min_distance=3)

    return sma200w_pct, div_sma200w


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
    ath_date = md["ath_date"]["usd"]  # ej: "2025-08-24T00:00:00.000Z"
    return ath, ath_change, ath_date


def get_fear_greed():
    req = urllib.request.Request(FNG_URL)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    entry = data["data"][0]
    value = int(entry["value"])
    classification = entry["value_classification"]
    return value, FNG_TRANSLATIONS.get(classification, classification)


def get_fear_greed_history(limit=400):
    """Devuelve un diccionario {'YYYY-MM-DD': valor int} con el historico de F&G."""
    params = urllib.parse.urlencode({"limit": limit, "format": "json"})
    url = f"https://api.alternative.me/fng/?{params}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    history = {}
    for entry in data["data"]:
        ts = int(entry["timestamp"])
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        history[date_str] = int(entry["value"])
    return history


def get_sth_realized_price():
    """Devuelve el ultimo valor del STH Realized Price (dato diario, no historico)."""
    url = "https://raw.githubusercontent.com/BGeometrics/bgeometrics.github.io/master/files/sth_realized_price_latest.csv"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        text = r.read().decode()
    lines = text.strip().split("\n")
    last_line = lines[-1]
    parts = last_line.split(",")
    return float(parts[2])


def read_sth_history(path="sth_history.txt"):
    """Devuelve una lista de (fecha, precio, sth_value, pct) en orden cronologico."""
    if not os.path.exists(path):
        return []
    history = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            date_str, price_str, sth_str, pct_str = line.split(",")
            history.append((date_str, float(price_str), float(sth_str), float(pct_str)))
    return history


def append_sth_history(price, sth_value, path="sth_history.txt"):
    """
    Guarda el dato de hoy (precio, STH, distancia %) si no se habia guardado ya.
    Construye poco a poco nuestro propio historico, ya que la fuente gratuita
    solo da el valor de hoy, no un historico completo.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = read_sth_history(path)
    existing_dates = {h[0] for h in history}
    if today_str in existing_dates:
        return False

    pct = None
    if sth_value:
        pct = ((price - sth_value) / sth_value) * 100

    with open(path, "a") as f:
        f.write(f"{today_str},{price},{sth_value},{pct}\n")
    return True


def detect_sth_divergence(path="sth_history.txt", order=2, min_distance=3):
    """
    Divergencia STH Realized Price, calculada sobre el historico propio que
    vamos construyendo dia a dia (no viene de una fuente externa).
    """
    history = read_sth_history(path)
    if len(history) < order * 2 + min_distance + 2:
        return "sin datos suficientes"

    prices = [h[1] for h in history]
    pcts = [h[3] for h in history]

    peaks, troughs = find_extrema(prices, order, min_distance)

    bearish = False
    if len(peaks) >= 2:
        i1, i2 = peaks[-2], peaks[-1]
        if prices[i2] > prices[i1] and pcts[i2] < pcts[i1]:
            bearish = True

    bullish = False
    if len(troughs) >= 2:
        i1, i2 = troughs[-2], troughs[-1]
        if prices[i2] < prices[i1] and pcts[i2] > pcts[i1]:
            bullish = True

    if bearish and bullish:
        return "⚠️ señales mixtas (revisar gráfico)"
    if bearish:
        return "🔻 divergencia bajista"
    if bullish:
        return "🔺 divergencia alcista"
    return "sin divergencia clara"


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


def compute_sma_distance_series(closes, period=200):
    """
    Devuelve la serie de distancia % del precio respecto a su SMA(period),
    calculada en cada punto donde ya hay suficiente historial (rolling).
    """
    if len(closes) < period + 1:
        return []

    distances = []
    for i in range(period, len(closes)):
        window = closes[i - period:i]
        sma = sum(window) / period
        if sma == 0:
            distances.append(0.0)
        else:
            distances.append(((closes[i] - sma) / sma) * 100)
    return distances


def detect_sma_divergence(closes, period=200, order=3, min_distance=5):
    """
    Version reducida (solo compara los 2 ultimos picos/valles, no un ciclo
    completo) de la misma logica que detect_divergence, pero usando la
    distancia % a una SMA(period) en vez del RSI. Sirve tanto para la SMA200
    diaria como para la SMA50 semanal, pasando el period/closes adecuados.
    """
    distances = compute_sma_distance_series(closes, period)
    if len(distances) < order * 2 + min_distance + 2:
        return "sin datos suficientes"

    aligned_closes = closes[-len(distances):]
    peaks, troughs = find_extrema(aligned_closes, order, min_distance)

    bearish = False
    if len(peaks) >= 2:
        i1, i2 = peaks[-2], peaks[-1]
        if aligned_closes[i2] > aligned_closes[i1] and distances[i2] < distances[i1]:
            bearish = True

    bullish = False
    if len(troughs) >= 2:
        i1, i2 = troughs[-2], troughs[-1]
        if aligned_closes[i2] < aligned_closes[i1] and distances[i2] > distances[i1]:
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
        return "🔺 tocando banda superior ⚠️ sobrecompra"
    if price <= lower:
        return "🔻 tocando banda inferior ⚠️ sobreventa"
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
    Devuelve 'alcista', 'bajista' o None (sin señal clara).
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
        return None  # volumen normal, sin confirmación extra

    if price_change > 0:
        return "alcista"
    if price_change < 0:
        return "bajista"
    return None


def compute_trend_summary(rsi_daily, rsi_weekly, rsi_monthly, macd_daily_hist,
                           macd_weekly_hist, boll_daily, boll_weekly, fng_value,
                           daily_closes, daily_volumes):
    # --- Corto plazo ---
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

    # --- Medio plazo ---
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

    # --- Largo plazo ---
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


def historical_zone_flag(pct, buy_threshold, sell_threshold, buy_strong=None, sell_strong=None):
    """
    Marca si un % de distancia entra en zona historica de capitulacion (compra)
    o de euforia (venta), segun umbrales de referencia del propio indicador.
    """
    if pct is None:
        return ""
    if buy_strong is not None and pct <= buy_strong:
        return " ⚠️ zona de capitulación histórica (fuerte)"
    if pct <= buy_threshold:
        return " ⚠️ zona de capitulación histórica"
    if sell_strong is not None and pct >= sell_strong:
        return " ⚠️ zona de euforia histórica (fuerte)"
    if pct >= sell_threshold:
        return " ⚠️ zona de euforia histórica"
    return ""


def read_last_report_tiers(path=LAST_REPORT_TIER_FILE):
    """
    Devuelve (tier_compra, tier_venta) del informe de AYER, o (None, None)
    si es la primera vez que corre (asi no mostramos "creciendo/decreciendo"
    sin tener con que comparar).
    """
    if os.path.exists(path):
        with open(path) as f:
            content = f.read().strip()
        if content:
            try:
                compra_str, venta_str = content.split(",")
                return int(compra_str), int(venta_str)
            except ValueError:
                pass
    return None, None


def write_last_report_tiers(tier_compra, tier_venta, path=LAST_REPORT_TIER_FILE):
    with open(path, "w") as f:
        f.write(f"{tier_compra},{tier_venta}")


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


def main():
    from strategy import evaluate_strict_signal

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
    div_sma200 = detect_sma_divergence(daily_closes, period=200, order=3, min_distance=5)
    div_sma50w = detect_sma_divergence(weekly_closes, period=50, order=2, min_distance=3)
    div_sth = detect_sth_divergence()

    boll_daily = compute_bollinger(daily_closes)
    boll_weekly = compute_bollinger(weekly_closes)
    boll_daily_signal = bollinger_signal(boll_daily)

    fng_value, fng_text = get_fear_greed()
    fng_emoji = FNG_EMOJIS.get(fng_text, "")

    ath, ath_change, ath_date = get_ath()

    try:
        sth_realized_price = get_sth_realized_price()
    except Exception as e:
        print(f"Aviso: no se pudo obtener STH Realized Price ({e})")
        sth_realized_price = None

    current_price = daily_closes[-1]

    # --- ATL real del ciclo actual (desde el ultimo ATH hasta hoy) ---
    try:
        ath_dt = datetime.strptime(ath_date, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        ath_ts = int(ath_dt.timestamp())
        now_ts = int(datetime.now(timezone.utc).timestamp())
        range_prices = get_price_range(ath_ts, now_ts)
        cycle_closes = [p for _, p in range_prices]
        if not cycle_closes:
            raise ValueError("rango vacio")
        atl_cycle = min(cycle_closes)
        atl_label = "mínimo desde el último ATH"
    except Exception as e:
        print(f"Aviso: no se pudo calcular el ATL del ciclo ({e}), usando fallback de 12 meses")
        atl_cycle = min(daily_closes)
        atl_label = "mínimo últimos 12 meses"

    atl_cycle_change = ((current_price - atl_cycle) / atl_cycle) * 100

    sma_200_daily = compute_sma(daily_closes, 200)
    sma_50_weekly = compute_sma(weekly_closes, 50)

    sth_pct = None
    if sth_realized_price:
        sth_pct = ((current_price - sth_realized_price) / sth_realized_price) * 100

    sma200_pct = None
    if sma_200_daily:
        sma200_pct = ((current_price - sma_200_daily) / sma_200_daily) * 100

    sma50w_pct = None
    if sma_50_weekly:
        sma50w_pct = ((current_price - sma_50_weekly) / sma_50_weekly) * 100

    alignment = build_alignment(rsi_daily, macd_daily_hist, div_daily, div_weekly, boll_daily_signal)

    sma200w_pct, div_sma200w = get_sma200_weekly_data(current_price)

    _, compra_items, venta_items = evaluate_strict_signal(
        daily_closes, weekly_closes, fng_value,
        sth_realized_price=sth_realized_price, sth_divergence=div_sth,
        sma200w_pct=sma200w_pct, div_sma200w=div_sma200w, required=8
    )
    compra_count = sum(1 for _, pts, _, _ in compra_items if pts >= 1)
    venta_count = sum(1 for _, pts, _, _ in venta_items if pts >= 1)
    total_conditions = len(compra_items)

    # --- Comparacion con el informe de ayer para creciendo/decreciendo ---
    last_report_compra, last_report_venta = read_last_report_tiers()
    trend_word = ""

    MIN_ZONE_TIER = 3
    if compra_count >= MIN_ZONE_TIER or venta_count >= MIN_ZONE_TIER:
        if compra_count > venta_count:
            if last_report_compra is not None:
                if compra_count > last_report_compra:
                    trend_word = " creciendo"
                elif compra_count < last_report_compra:
                    trend_word = " decreciendo"
            stars = "⭐️" * compra_count
            zone_text = f"🟢 Zona de compra{trend_word} ({compra_count}/{total_conditions}) {stars}"
        elif venta_count > compra_count:
            if last_report_venta is not None:
                if venta_count > last_report_venta:
                    trend_word = " creciendo"
                elif venta_count < last_report_venta:
                    trend_word = " decreciendo"
            stars = "⭐️" * venta_count
            zone_text = f"🔴 Zona de venta{trend_word} ({venta_count}/{total_conditions}) {stars}"
        else:
            zone_text = f"⚠️ Zona mixta (compra {compra_count}/{total_conditions}, venta {venta_count}/{total_conditions})"
    else:
        zone_text = "➖ Zona neutral"

    write_last_report_tiers(compra_count, venta_count)

    corto, medio, largo = compute_trend_summary(
        rsi_daily, rsi_weekly, rsi_monthly,
        macd_daily_hist, macd_weekly_hist,
        boll_daily, boll_weekly, fng_value,
        daily_closes, daily_volumes,
    )

    lines = [
        "📊 Informe diario BTC",
        "----------------------------------",
        f"Zona: {zone_text}",
        "----------------------------------",
        f"Fear & Greed: {fng_emoji} {fng_text} ({fng_value})",
        f"RSI diario: {rsi_daily:.0f}{zone_flag(rsi_daily)}",
        f"RSI semanal: {rsi_weekly:.0f}{zone_flag(rsi_weekly)}",
        f"RSI mensual: {rsi_monthly:.0f}{zone_flag(rsi_monthly)}",
        "----------------------------------",
        f"MACD diario: {describe_macd(macd_daily_hist)}",
        f"MACD semanal: {describe_macd(macd_weekly_hist)}",
        "----------------------------------",
        f"Divergencia RSI diario: {div_daily}",
        f"Divergencia RSI semanal: {div_weekly}",
        f"Divergencia SMA200 diario: {div_sma200}",
        f"Divergencia SMA50 semanal: {div_sma50w}",
        f"Divergencia STH Realized Price: {div_sth}",
        "----------------------------------",
        f"Bollinger diario: {describe_bollinger(boll_daily)}",
        f"Bollinger semanal: {describe_bollinger(boll_weekly)}",
        "----------------------------------",
        f"ATH: {ath:,.0f} $ ({ath_change:.1f}%)",
        f"ATL: {atl_cycle:,.0f} $ ({atl_cycle_change:+.1f}%) ({atl_label})",
        "----------------------------------",
    ]

    if sth_pct is not None:
        flag = historical_zone_flag(sth_pct, buy_threshold=-10, sell_threshold=30)
        lines.append(f"Distancia a STH Realized Price: {sth_pct:+.1f}%{flag}")
    if sma200_pct is not None:
        flag = historical_zone_flag(sma200_pct, buy_threshold=-25, sell_threshold=45)
        lines.append(f"Distancia a SMA200 diario: {sma200_pct:+.1f}%{flag}")
    if sma50w_pct is not None:
        flag = historical_zone_flag(sma50w_pct, buy_threshold=-20, sell_threshold=60)
        lines.append(f"Distancia a SMA50 semanal: {sma50w_pct:+.1f}%{flag}")
    if sma200w_pct is not None:
        flag = historical_zone_flag(sma200w_pct, buy_threshold=-5, sell_threshold=100)
        lines.append(f"Distancia a SMA200 semanal: {sma200w_pct:+.1f}%{flag}")
        lines.append(f"Divergencia SMA200 semanal: {div_sma200w}")

    lines += [
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
