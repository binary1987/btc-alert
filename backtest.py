#!/usr/bin/env python3
import os
import urllib.request
import urllib.parse

from report import (
    get_market_chart,
    group_last,
    compute_rsi,
    compute_macd_histogram,
    macd_cross_direction,
    detect_divergence,
    compute_bollinger,
    bollinger_signal,
    compute_roc,
    compute_sma,
    compute_volume_confirmation,
)

STATE_FILE = "last_signal.txt"
THRESHOLD = 5  # numero minimo de indicadores alineados para considerar la señal "clara"


def read_last_signal():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return f.read().strip()
    return None


def write_last_signal(value):
    with open(STATE_FILE, "w") as f:
        f.write(value)


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


def evaluate_signal(daily_closes, daily_volumes, weekly_closes):
    """Cuenta cuantos indicadores apuntan a alcista vs bajista. Devuelve (votos_alcistas, votos_bajistas)."""
    rsi_daily = compute_rsi(daily_closes)
    macd_daily_hist = compute_macd_histogram(daily_closes)
    div_daily = detect_divergence(daily_closes, order=3, min_distance=5)
    div_weekly = detect_divergence(weekly_closes, order=2, min_distance=3)
    boll_daily = compute_bollinger(daily_closes)

    bullish_votes = []
    bearish_votes = []

    if rsi_daily is not None:
        if rsi_daily <= 25:
            bullish_votes.append("RSI diario en sobreventa")
        elif rsi_daily >= 75:
            bearish_votes.append("RSI diario en sobrecompra")

    cross = macd_cross_direction(macd_daily_hist)
    if cross == "alcista":
        bullish_votes.append("MACD diario cruce alcista")
    elif cross == "bajista":
        bearish_votes.append("MACD diario cruce bajista")

    if "alcista" in div_daily:
        bullish_votes.append("divergencia diaria alcista")
    elif "bajista" in div_daily:
        bearish_votes.append("divergencia diaria bajista")

    if "alcista" in div_weekly:
        bullish_votes.append("divergencia semanal alcista")
    elif "bajista" in div_weekly:
        bearish_votes.append("divergencia semanal bajista")

    boll_sig = bollinger_signal(boll_daily)
    if boll_sig == "sobreventa":
        bullish_votes.append("Bollinger diario en sobreventa")
    elif boll_sig == "sobrecompra":
        bearish_votes.append("Bollinger diario en sobrecompra")

    roc_7 = compute_roc(daily_closes, 7)
    if roc_7 is not None:
        if roc_7 > 0:
            bullish_votes.append("ROC 7d positivo")
        else:
            bearish_votes.append("ROC 7d negativo")

    sma50 = compute_sma(daily_closes, 50)
    sma200 = compute_sma(daily_closes, 200)
    if sma50 is not None and sma200 is not None:
        if sma50 > sma200:
            bullish_votes.append("SMA50 > SMA200")
        else:
            bearish_votes.append("SMA50 < SMA200")

    vol_confirm = compute_volume_confirmation(daily_closes, daily_volumes)
    if vol_confirm == "alcista":
        bullish_votes.append("volumen confirma subida")
    elif vol_confirm == "bajista":
        bearish_votes.append("volumen confirma bajada")

    return bullish_votes, bearish_votes


def main():
    prices, volumes = get_market_chart(days=365)
    daily_closes = [p for _, p in prices]
    daily_volumes = [v for _, v in volumes]
    weekly_closes = group_last(prices, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))

    bullish_votes, bearish_votes = evaluate_signal(daily_closes, daily_volumes, weekly_closes)

    current_signal = None
    reasons = []
    if len(bullish_votes) >= THRESHOLD:
        current_signal = "COMPRA"
        reasons = bullish_votes
    elif len(bearish_votes) >= THRESHOLD:
        current_signal = "VENTA"
        reasons = bearish_votes

    last_signal = read_last_signal()

    print(f"Alcistas: {len(bullish_votes)} {bullish_votes}")
    print(f"Bajistas: {len(bearish_votes)} {bearish_votes}")
    print(f"Señal actual: {current_signal} | Última guardada: {last_signal!r}")

    if last_signal is None:
        write_last_signal(current_signal or "")
        return

    if current_signal and current_signal != last_signal:
        emoji = "🟢" if current_signal == "COMPRA" else "🔴"
        count = len(reasons)
        msg = (
            f"🚦 SEÑAL: {current_signal} {emoji}\n"
            f"{count} indicadores alineados:\n"
            + "\n".join(f"- {r}" for r in reasons)
            + "\n\n⚠️ Esto es un análisis técnico automático, no es consejo financiero."
        )
        print("AVISO:", msg)
        send_telegram(msg)
        write_last_signal(current_signal)
    elif not current_signal and last_signal:
        write_last_signal("")


if __name__ == "__main__":
    main()
