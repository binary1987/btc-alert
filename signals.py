#!/usr/bin/env python3
import os
import urllib.request
import urllib.parse

from report import get_market_chart, group_last, get_fear_greed
from strategy import evaluate_strict_signal

STATE_FILE = "last_tier.txt"
MIN_TIER_TO_NOTIFY = 3  # a partir de 3/5 empezamos a avisar


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


def build_message(direction, tier, conditions):
    emoji = "🟢" if direction == "COMPRA" else "🔴"
    estrellas = "⭐" * tier
    cumplidas = [name for name, met in conditions.items() if met]
    lines = [f"🔔 Nivel {direction} {tier}/5 {emoji} {estrellas}", "Condiciones cumplidas:"]
    lines += [f"- {c}" for c in cumplidas]
    return "\n".join(lines)


def main():
    prices, volumes = get_market_chart(days=365)
    daily_closes = [p for _, p in prices]
    weekly_closes = group_last(prices, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))

    fng_value, _ = get_fear_greed()

    _, cond_compra, cond_venta = evaluate_strict_signal(
        daily_closes, weekly_closes, fng_value, required=5
    )

    tier_compra_now = sum(cond_compra.values())
    tier_venta_now = sum(cond_venta.values())

    last_compra, last_venta = read_last_tiers()

    print(f"Nivel COMPRA actual: {tier_compra_now}/5 (anterior: {last_compra})")
    print(f"Nivel VENTA actual: {tier_venta_now}/5 (anterior: {last_venta})")

    notify_compra = tier_compra_now >= MIN_TIER_TO_NOTIFY and tier_compra_now > last_compra
    notify_venta = tier_venta_now >= MIN_TIER_TO_NOTIFY and tier_venta_now > last_venta

    if notify_compra:
        msg = build_message("COMPRA", tier_compra_now, cond_compra)
        print("AVISO:", msg)
        send_telegram(msg)

    if notify_venta:
        msg = build_message("VENTA", tier_venta_now, cond_venta)
        print("AVISO:", msg)
        send_telegram(msg)

    write_last_tiers(tier_compra_now, tier_venta_now)


if __name__ == "__main__":
    main()
