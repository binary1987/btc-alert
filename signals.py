#!/usr/bin/env python3
import os
import urllib.request
import urllib.parse

from report import get_market_chart, group_last, get_fear_greed, get_sth_realized_price
from strategy import evaluate_strict_signal

STATE_FILE = "last_tier.txt"
MIN_TIER_TO_NOTIFY = 3  # a partir de 3 condiciones activas empezamos a avisar


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


def build_message(direction, items):
    conditions_met = sum(1 for _, pts, _, _, _ in items if pts >= 1)
    total_conditions = len(items)
    score = sum(pts for _, pts, _, _, _ in items)
    max_score = sum(2 if unit == "%" else 1 for _, _, _, unit, _ in items)

    emoji = "🟢" if direction == "COMPRA" else "🔴"
    label = "ZONA DE COMPRA" if direction == "COMPRA" else "ZONA DE VENTA"
    estrellas = "⭐️" * conditions_met

    lines = [
        f"🔔{emoji} {label} {estrellas}",
        f"Condiciones cumplidas: {conditions_met}/{total_conditions}",
        f"Puntuación ponderada: {score}/{max_score}",
        "",
    ]

    for text, pts, value, unit, is_strong in items:
        check = "✅" if pts >= 1 else "❌"
        line = f"{check} {text}"
        if value is not None:
            if unit == "%":
                line += f": {value:+.0f}%"
            else:
                line += f": {value:.0f}"
        if is_strong:
            line += " 🔥 (fuerte)"
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

    _, compra_items, venta_items = evaluate_strict_signal(
        daily_closes, weekly_closes, fng_value, sth_realized_price=sth_realized_price, required=8
    )

    tier_compra_now = sum(1 for _, pts, _, _, _ in compra_items if pts >= 1)
    tier_venta_now = sum(1 for _, pts, _, _, _ in venta_items if pts >= 1)

    last_compra, last_venta = read_last_tiers()

    print(f"Nivel COMPRA actual: {tier_compra_now}/{len(compra_items)} (anterior: {last_compra})")
    print(f"Nivel VENTA actual: {tier_venta_now}/{len(venta_items)} (anterior: {last_venta})")

    notify_compra = tier_compra_now >= MIN_TIER_TO_NOTIFY and tier_compra_now > last_compra
    notify_venta = tier_venta_now >= MIN_TIER_TO_NOTIFY and tier_venta_now > last_venta

    if notify_compra:
        msg = build_message("COMPRA", compra_items)
        print("AVISO:", msg)
        send_telegram(msg)

    if notify_venta:
        msg = build_message("VENTA", venta_items)
        print("AVISO:", msg)
        send_telegram(msg)

    write_last_tiers(tier_compra_now, tier_venta_now)


if __name__ == "__main__":
    main()
