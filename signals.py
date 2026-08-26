#!/usr/bin/env python3
import os
import urllib.request
import urllib.parse

from report import get_market_chart, group_last, get_fear_greed, get_sth_realized_price
from strategy import evaluate_strict_signal

STATE_FILE = "last_tier.txt"
MIN_TIER_TO_NOTIFY = 3  # a partir de 3 condiciones empezamos a avisar

# Ranking fijo de importancia (1 = mas importante). Debe coincidir con las
# claves usadas en strategy.evaluate_strict_signal para COMPRA y VENTA.
IMPORTANCE_RANK_COMPRA = {
    "Precio 10% por debajo de STH Realized Price": 1,
    "RSI semanal <= 40": 2,
    "MACD linea < 0": 3,
    "F&G <= 46": 4,
    "RSI diario <= 25": 5,
    "MACD rojo claro perdiendo fuerza": 6,
}

IMPORTANCE_RANK_VENTA = {
    "Precio 10% por encima de STH Realized Price": 1,
    "RSI semanal >= 60": 2,
    "MACD linea > 0": 3,
    "F&G >= 55": 4,
    "RSI diario >= 75": 5,
    "MACD verde claro perdiendo fuerza": 6,
}

STH_CONDITION_NAMES = {
    "Precio 10% por debajo de STH Realized Price",
    "Precio 10% por encima de STH Realized Price",
}


def read_last_tiers():
    """Devuelve (tier_compra, tier_venta) guardados, o (0, 0) si no existe estado previo."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            content = f.read().strip()
        if content:
            try:
                compra_str, venta_str = content.split(",")
                return int(compra_str), int(venta_str)
            except ValueError:
                pass
    return 0, 0


def write_last_tiers(tier_compra, tier_venta):
    with open(STATE_FILE, "w") as f:
        f.write(f"{tier_compra},{tier_venta}")


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


def build_message(direction, tier, conditions, rank_map, sth_pct=None):
    emoji = "🟢" if direction == "COMPRA" else "🔴"
    total = len(conditions)
    estrellas = "⭐️" * tier

    cumplidas = [(rank_map.get(name, 99), name) for name, met in conditions.items() if met]
    cumplidas.sort(key=lambda x: x[0])

    lines = [
        f"🔔{emoji} {direction} {estrellas}",
        f"Condiciones cumplidas: {tier}/{total}",
    ]
    for rank, name in cumplidas:
        line = f"{rank}. {name}"
        if sth_pct is not None and name in STH_CONDITION_NAMES:
            line += f": {sth_pct:+.0f}%"
        lines.append(line)
    return "\n".join(lines)


def main():
    prices, volumes = get_market_chart(days=365)
    daily_closes = [p for _, p in prices]
    weekly_closes = group_last(prices, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))

    fng_value, _ = get_fear_greed()

    try:
        sth_realized_price = get_sth_realized_price()
    except Exception as e:
        print(f"Aviso: no se pudo obtener STH Realized Price ({e}), se ignora esa condicion")
        sth_realized_price = None

    _, cond_compra, cond_venta, sth_pct = evaluate_strict_signal(
        daily_closes, weekly_closes, fng_value, sth_realized_price=sth_realized_price, required=6
    )

    tier_compra_now = sum(cond_compra.values())
    tier_venta_now = sum(cond_venta.values())

    last_compra, last_venta = read_last_tiers()

    print(f"Nivel COMPRA actual: {tier_compra_now}/{len(cond_compra)} (anterior: {last_compra})")
    print(f"Nivel VENTA actual: {tier_venta_now}/{len(cond_venta)} (anterior: {last_venta})")
    if sth_pct is not None:
        print(f"Distancia actual al STH Realized Price: {sth_pct:+.1f}%")

    notify_compra = tier_compra_now >= MIN_TIER_TO_NOTIFY and tier_compra_now > last_compra
    notify_venta = tier_venta_now >= MIN_TIER_TO_NOTIFY and tier_venta_now > last_venta

    if notify_compra:
        msg = build_message("COMPRA", tier_compra_now, cond_compra, IMPORTANCE_RANK_COMPRA, sth_pct)
        print("AVISO:", msg)
        send_telegram(msg)

    if notify_venta:
        msg = build_message("VENTA", tier_venta_now, cond_venta, IMPORTANCE_RANK_VENTA, sth_pct)
        print("AVISO:", msg)
        send_telegram(msg)

    write_last_tiers(tier_compra_now, tier_venta_now)


if __name__ == "__main__":
    main()
