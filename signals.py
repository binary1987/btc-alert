#!/usr/bin/env python3
import os
import json
import urllib.request
import urllib.parse

from report import (
    get_market_chart, group_last, group_sum, get_fear_greed, get_sth_realized_price,
    append_sth_history, detect_sth_divergence, get_sma200_weekly_data,
)
from strategy import evaluate_strict_signal

STATE_FILE = "last_tier.txt"
MIN_TIER_TO_NOTIFY = 3  # a partir de 3 condiciones activas empezamos a avisar


def read_last_state():
    """
    Devuelve un dict {tier_compra, tier_venta, active_compra, active_venta}.
    Si no existe estado previo, devuelve valores por defecto en 0/listas vacias.
    """
    default = {"tier_compra": 0, "tier_venta": 0, "active_compra": [], "active_venta": []}
    if not os.path.exists(STATE_FILE):
        return default
    try:
        with open(STATE_FILE) as f:
            content = f.read().strip()
        if not content:
            return default
        data = json.loads(content)
        for key in default:
            data.setdefault(key, default[key])
        return data
    except (json.JSONDecodeError, ValueError):
        return default


def write_last_state(tier_compra, tier_venta, active_compra, active_venta):
    data = {
        "tier_compra": tier_compra,
        "tier_venta": tier_venta,
        "active_compra": active_compra,
        "active_venta": active_venta,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


def build_message(direction, items):
    """Mensaje completo con las condiciones, usado cuando el nivel SUBE."""
    conditions_met = sum(1 for _, pts, _, _ in items if pts >= 1)
    total_conditions = len(items)

    emoji = "🟢" if direction == "COMPRA" else "🔴"
    label = "ZONA DE COMPRA" if direction == "COMPRA" else "ZONA DE VENTA"
    estrellas = "⭐️" * conditions_met

    lines = [
        f"🔔{emoji} {label} {estrellas}",
        f"Condiciones cumplidas: {conditions_met}/{total_conditions}",
        "",
    ]

    for text, pts, value, unit in items:
        check = "✅" if pts >= 1 else "❌"
        line = f"{check} {text}"
        if value is not None:
            if unit == "%":
                line += f": {value:+.0f}%"
            else:
                line += f": {value:.0f}"
        lines.append(line)

    return "\n".join(lines)


def build_decrease_message(direction, new_tier, old_tier, dropped_conditions):
    """Mensaje cuando el nivel BAJA pero se mantiene dentro de la zona de aviso (>=3)."""
    label = "Zona de compra" if direction == "COMPRA" else "Zona de venta"
    estrellas = "⭐️" * new_tier

    lines = [
        f"🔔📉 {label} decreciendo {estrellas}",
        f"Pasamos de {old_tier} a {new_tier} condiciones cumplidas",
    ]

    if dropped_conditions:
        lines.append("")
        lines.append("Dejó de cumplirse:")
        for c in dropped_conditions:
            lines.append(f"- {c}")

    return "\n".join(lines)


def build_deactivated_message(direction, new_tier, old_tier):
    """Mensaje cuando el nivel BAJA por debajo del umbral de aviso (sale de la zona)."""
    label = "ZONA DE COMPRA" if direction == "COMPRA" else "ZONA DE VENTA"
    return "\n".join([
        f"🔔📉 {label} YA NO ACTIVA",
        f"Pasamos de {old_tier} a {new_tier} condiciones cumplidas",
    ])


def process_direction(direction, items, last_tier, last_active):
    """
    Evalua un lado (COMPRA o VENTA), decide si hay que avisar, envia el
    mensaje correspondiente, y devuelve (tier_actual, lista_activas_actual).
    """
    current_tier = sum(1 for _, pts, _, _ in items if pts >= 1)
    current_active = [text for text, pts, _, _ in items if pts >= 1]

    if current_tier > last_tier and current_tier >= MIN_TIER_TO_NOTIFY:
        msg = build_message(direction, items)
        print(f"AVISO ({direction}, sube):", msg)
        send_telegram(msg)

    elif current_tier < last_tier:
        if current_tier >= MIN_TIER_TO_NOTIFY:
            dropped = [c for c in last_active if c not in current_active]
            msg = build_decrease_message(direction, current_tier, last_tier, dropped)
            print(f"AVISO ({direction}, decrece):", msg)
            send_telegram(msg)
        elif last_tier >= MIN_TIER_TO_NOTIFY:
            msg = build_deactivated_message(direction, current_tier, last_tier)
            print(f"AVISO ({direction}, desactivada):", msg)
            send_telegram(msg)

    return current_tier, current_active


def main():
    prices, volumes = get_market_chart(days=365)
    daily_closes = [p for _, p in prices]
    daily_volumes = [v for _, v in volumes]
    weekly_closes = group_last(prices, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))
    weekly_volumes = group_sum(volumes, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))

    fng_value, _ = get_fear_greed()

    try:
        sth_realized_price = get_sth_realized_price()
    except Exception as e:
        print(f"Aviso: no se pudo obtener STH Realized Price ({e}), se ignora esa condicion")
        sth_realized_price = None

    if sth_realized_price is not None:
        saved = append_sth_history(daily_closes[-1], sth_realized_price)
        print(f"Historico STH actualizado hoy: {saved}")

    sth_divergence = detect_sth_divergence()
    print(f"Divergencia STH: {sth_divergence}")

    sma200w_pct, div_sma200w = get_sma200_weekly_data(daily_closes[-1])
    print(f"SMA200 semanal: {sma200w_pct}, divergencia: {div_sma200w}")

    _, compra_items, venta_items = evaluate_strict_signal(
        daily_closes, weekly_closes, fng_value,
        sth_realized_price=sth_realized_price,
        sth_divergence=sth_divergence,
        sma200w_pct=sma200w_pct,
        div_sma200w=div_sma200w,
        daily_volumes=daily_volumes,
        weekly_volumes=weekly_volumes,
        required=8,
    )

    state = read_last_state()

    print(f"Nivel COMPRA anterior: {state['tier_compra']}")
    print(f"Nivel VENTA anterior: {state['tier_venta']}")

    tier_compra_now, active_compra_now = process_direction(
        "COMPRA", compra_items, state["tier_compra"], state["active_compra"]
    )
    tier_venta_now, active_venta_now = process_direction(
        "VENTA", venta_items, state["tier_venta"], state["active_venta"]
    )

    print(f"Nivel COMPRA actual: {tier_compra_now}/{len(compra_items)}")
    print(f"Nivel VENTA actual: {tier_venta_now}/{len(venta_items)}")

    write_last_state(tier_compra_now, tier_venta_now, active_compra_now, active_venta_now)


if __name__ == "__main__":
    main()
