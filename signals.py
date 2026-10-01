#!/usr/bin/env python3
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

from report import (
    get_market_chart, group_last, group_sum, get_fear_greed, get_sth_realized_price,
    append_sth_history, detect_sth_divergence, get_sma200_weekly_data,
    get_btc_daily_ohlc_twelvedata, compute_last_closed_week_range,
    compute_last_closed_month_range,
)
from strategy import evaluate_strict_signal

STATE_FILE = "last_tier.txt"
MIN_TIER_TO_NOTIFY = 3  # a partir de 3 condiciones activas empezamos a avisar

WEEKLY_RANGE_STATE_FILE = "weekly_range_state.json"
MONTHLY_RANGE_STATE_FILE = "monthly_range_state.json"
WEEKLY_STREAK_STATE_FILE = "weekly_streak_state.json"
MONTHLY_STREAK_STATE_FILE = "monthly_streak_state.json"
WATCHED_LEVELS_FILE = "watched_levels_state.json"

MESES_ES_ABR = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_ES_FULL = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


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


def format_condition_line(check, text, value, unit):
    line = f"{check} {text}"
    if value is not None:
        if unit == "%":
            line += f": {value:+.0f}%"
        else:
            line += f": {value:.0f}"
    return line


def build_message(direction, items, last_active=None):
    """
    Mensaje completo con las condiciones, usado cuando el nivel SUBE.
    Primero muestra que condicion(es) nueva(s) empezaron a cumplirse desde
    el nivel anterior (comparando con last_active), y despues separa el
    resto en dos bloques: activas y no activas.
    """
    conditions_met = sum(1 for _, pts, _, _ in items if pts >= 1)
    total_conditions = len(items)

    emoji = "🟢" if direction == "COMPRA" else "🔴"
    label = "ZONA DE COMPRA" if direction == "COMPRA" else "ZONA DE VENTA"
    estrellas = "⭐️" * conditions_met

    active = [(text, value, unit) for text, pts, value, unit in items if pts >= 1]
    inactive = [(text, value, unit) for text, pts, value, unit in items if pts < 1]

    last_active = last_active or []
    new_active = [(text, value, unit) for text, value, unit in active if text not in last_active]

    lines = [
        f"🔔{emoji} {label} {estrellas}",
        f"Condiciones cumplidas: {conditions_met}/{total_conditions}",
        "",
        "🆕 Empezó a cumplirse:",
    ]

    if new_active:
        for text, value, unit in new_active:
            lines.append(format_condition_line("✅", text, value, unit))
    else:
        lines.append("(ninguna)")

    lines.append("")
    lines.append("✅ Activas:")

    if active:
        for text, value, unit in active:
            lines.append(format_condition_line("✅", text, value, unit))
    else:
        lines.append("(ninguna)")

    lines.append("")
    lines.append("❌ No activas:")

    if inactive:
        for text, value, unit in inactive:
            lines.append(format_condition_line("❌", text, value, unit))
    else:
        lines.append("(ninguna)")

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


def process_direction(direction, items, last_tier, last_active, veto=False):
    """
    Evalua un lado (COMPRA o VENTA), decide si hay que avisar, envia el
    mensaje correspondiente, y devuelve (tier_actual, lista_activas_actual).

    El veto (RSI diario + F&G contradicen esta zona) bloquea los mensajes
    de "sube" y "decrece" (que siguen afirmando que la zona esta activa),
    pero NUNCA bloquea el mensaje de "YA NO ACTIVA": ese solo informa de
    que la zona se desactivo, no contradice nada del contexto, y conviene
    que siempre llegue para no dejar al usuario pensando que sigue activa.
    """
    current_tier = sum(1 for _, pts, _, _ in items if pts >= 1)
    current_active = [text for text, pts, _, _ in items if pts >= 1]

    if current_tier > last_tier and current_tier >= MIN_TIER_TO_NOTIFY:
        if veto:
            print(f"{direction}: nivel {current_tier} pero VETADO por contexto (RSI+F&G), no se avisa (subida)")
        else:
            msg = build_message(direction, items, last_active)
            print(f"AVISO ({direction}, sube):", msg)
            send_telegram(msg)

    elif current_tier < last_tier:
        if current_tier >= MIN_TIER_TO_NOTIFY:
            if veto:
                print(f"{direction}: nivel {current_tier} pero VETADO por contexto (RSI+F&G), no se avisa (decrece)")
            else:
                dropped = [c for c in last_active if c not in current_active]
                msg = build_decrease_message(direction, current_tier, last_tier, dropped)
                print(f"AVISO ({direction}, decrece):", msg)
                send_telegram(msg)
        elif last_tier >= MIN_TIER_TO_NOTIFY:
            # La desactivacion siempre se avisa, pase lo que pase con el veto.
            msg = build_deactivated_message(direction, current_tier, last_tier)
            print(f"AVISO ({direction}, desactivada):", msg)
            send_telegram(msg)

    return current_tier, current_active


def read_range_state(path):
    default = {"key": None, "high": None, "low": None, "alerted_up": False, "alerted_down": False}
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            content = f.read().strip()
        if not content:
            return default
        data = json.loads(content)
        for k in default:
            data.setdefault(k, default[k])
        return data
    except (json.JSONDecodeError, ValueError):
        return default


def write_range_state(path, key, high, low, alerted_up, alerted_down):
    data = {
        "key": key,
        "high": high,
        "low": low,
        "alerted_up": alerted_up,
        "alerted_down": alerted_down,
    }
    with open(path, "w") as f:
        json.dump(data, f)


def read_streak_state(path):
    default = {"up_streak": [], "down_streak": []}
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            content = f.read().strip()
        if not content:
            return default
        data = json.loads(content)
        for k in default:
            data.setdefault(k, default[k])
        return data
    except (json.JSONDecodeError, ValueError):
        return default


def write_streak_state(path, up_streak, down_streak):
    data = {"up_streak": up_streak, "down_streak": down_streak}
    with open(path, "w") as f:
        json.dump(data, f)


def read_watched_levels():
    default = {"weekly_max": None, "weekly_min": None, "monthly_max": None, "monthly_min": None}
    if not os.path.exists(WATCHED_LEVELS_FILE):
        return default
    try:
        with open(WATCHED_LEVELS_FILE) as f:
            content = f.read().strip()
        if not content:
            return default
        data = json.loads(content)
        for k in default:
            data.setdefault(k, default[k])
        return data
    except (json.JSONDecodeError, ValueError):
        return default


def write_watched_levels(data):
    with open(WATCHED_LEVELS_FILE, "w") as f:
        json.dump(data, f)


def set_watched_level(slot, value, label):
    """
    Marca un nuevo maximo/minimo relativo como "vigilado" (pendiente de
    romperse). Si ya habia uno vigilado en ese mismo slot (mismo plano,
    misma direccion), lo sustituye: el mas reciente es el relevante.
    """
    data = read_watched_levels()
    data[slot] = {"value": value, "label": label, "alerted": False}
    write_watched_levels(data)


def week_key_to_label(week_key):
    """Convierte '2026-W38' en algo legible tipo '15-21 sep'."""
    year_str, week_str = week_key.split("-W")
    year, week = int(year_str), int(week_str)
    monday = datetime.fromisocalendar(year, week, 1).date()
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"{monday.day}-{sunday.day} {MESES_ES_ABR[monday.month - 1]}"
    return f"{monday.day} {MESES_ES_ABR[monday.month - 1]} - {sunday.day} {MESES_ES_ABR[sunday.month - 1]}"


def month_key_to_label(month_key):
    """Convierte '2026-08' en 'agosto'."""
    _, month_str = month_key.split("-")
    return MESES_ES_FULL[int(month_str) - 1]


def describe_weekly_streak(direction):
    """
    Describe el estado ACTUAL (ya confirmado, sin contar la semana en
    curso) de la racha semanal en una direccion ('up' o 'down').
    """
    state = read_streak_state(WEEKLY_STREAK_STATE_FILE)
    entries = state["up_streak"] if direction == "up" else state["down_streak"]
    n = len(entries)
    word = "máximos" if direction == "up" else "mínimos"
    if n == 0:
        return f"sin ruptura de {word} la última semana cerrada"
    labels = ", ".join(week_key_to_label(e["key"]) for e in entries)
    return f"{n} semana{'s' if n != 1 else ''} consecutiva{'s' if n != 1 else ''} rompiendo {word} ({labels})"


def describe_monthly_streak(direction):
    """Igual que describe_weekly_streak pero para el plano mensual."""
    state = read_streak_state(MONTHLY_STREAK_STATE_FILE)
    entries = state["up_streak"] if direction == "up" else state["down_streak"]
    n = len(entries)
    word = "máximos" if direction == "up" else "mínimos"
    if n == 0:
        return f"sin ruptura de {word} el último mes cerrado"
    labels = ", ".join(month_key_to_label(e["key"]) for e in entries)
    return f"{n} mes{'es' if n != 1 else ''} consecutivo{'s' if n != 1 else ''} rompiendo {word} ({labels})"


def confirm_weekly_streak(just_closed_key, high, low, broke_up, broke_down):
    """
    Se llama justo cuando una semana termina de cerrarse (detectado en el
    siguiente chequeo horario). broke_up/broke_down son los flags de esa
    semana ya cerrada: si en algun momento de esa semana el precio rompio
    el maximo/minimo de la semana anterior a ella.

    Si rompio, esa semana se añade a la racha correspondiente. Si no
    rompio, esa racha se corta: si tenia contenido previo, se avisa del
    maximo/minimo relativo que deja esa racha cortada, y ese nivel queda
    vigilado para avisar tambien cuando el precio lo rompa mas adelante.
    """
    state = read_streak_state(WEEKLY_STREAK_STATE_FILE)
    up_streak = state["up_streak"]
    down_streak = state["down_streak"]
    entry = {"key": just_closed_key, "high": high, "low": low}

    if broke_up:
        up_streak.append(entry)
    else:
        if up_streak:
            peak = max(up_streak, key=lambda e: e["high"])
            n = len(up_streak)
            label = f"semana {week_key_to_label(peak['key'])}"
            msg = "\n".join([
                f"🔄 BTC pierde la racha alcista semanal ({n} semana{'s' if n != 1 else ''} consecutiva{'s' if n != 1 else ''})",
                f"Máximo relativo dejado: {peak['high']:,.0f} $ ({label})",
            ])
            print("AVISO (fin racha alcista semanal):", msg)
            send_telegram(msg)
            set_watched_level("weekly_max", peak["high"], label)
        up_streak = []

    if broke_down:
        down_streak.append(entry)
    else:
        if down_streak:
            trough = min(down_streak, key=lambda e: e["low"])
            n = len(down_streak)
            label = f"semana {week_key_to_label(trough['key'])}"
            msg = "\n".join([
                f"🔄 BTC pierde la racha bajista semanal ({n} semana{'s' if n != 1 else ''} consecutiva{'s' if n != 1 else ''})",
                f"Mínimo relativo dejado: {trough['low']:,.0f} $ ({label})",
            ])
            print("AVISO (fin racha bajista semanal):", msg)
            send_telegram(msg)
            set_watched_level("weekly_min", trough["low"], label)
        down_streak = []

    write_streak_state(WEEKLY_STREAK_STATE_FILE, up_streak, down_streak)


def confirm_monthly_streak(just_closed_key, high, low, broke_up, broke_down):
    """Igual que confirm_weekly_streak pero para el plano mensual."""
    state = read_streak_state(MONTHLY_STREAK_STATE_FILE)
    up_streak = state["up_streak"]
    down_streak = state["down_streak"]
    entry = {"key": just_closed_key, "high": high, "low": low}

    if broke_up:
        up_streak.append(entry)
    else:
        if up_streak:
            peak = max(up_streak, key=lambda e: e["high"])
            n = len(up_streak)
            label = month_key_to_label(peak["key"])
            msg = "\n".join([
                f"🔄 BTC pierde la racha alcista mensual ({n} mes{'es' if n != 1 else ''} consecutivo{'s' if n != 1 else ''})",
                f"Máximo relativo dejado: {peak['high']:,.0f} $ ({label})",
            ])
            print("AVISO (fin racha alcista mensual):", msg)
            send_telegram(msg)
            set_watched_level("monthly_max", peak["high"], label)
        up_streak = []

    if broke_down:
        down_streak.append(entry)
    else:
        if down_streak:
            trough = min(down_streak, key=lambda e: e["low"])
            n = len(down_streak)
            label = month_key_to_label(trough["key"])
            msg = "\n".join([
                f"🔄 BTC pierde la racha bajista mensual ({n} mes{'es' if n != 1 else ''} consecutivo{'s' if n != 1 else ''})",
                f"Mínimo relativo dejado: {trough['low']:,.0f} $ ({label})",
            ])
            print("AVISO (fin racha bajista mensual):", msg)
            send_telegram(msg)
            set_watched_level("monthly_min", trough["low"], label)
        down_streak = []

    write_streak_state(MONTHLY_STREAK_STATE_FILE, up_streak, down_streak)


def build_relative_level_message(slot, current_price, level):
    value = level["value"]
    label = level["label"]
    pct = ((current_price - value) / value) * 100 if value else 0
    scope_word = "SEMANAL" if slot.startswith("weekly") else "MENSUAL"

    if slot.endswith("_max"):
        return "\n".join([
            f"🔔📈 BTC ROMPE MÁXIMO RELATIVO {scope_word} ANTERIOR",
            f"Precio actual: {current_price:,.0f} $",
            f"Máximo relativo ({label}): {value:,.0f} $ ({pct:+.1f}%)",
        ])
    return "\n".join([
        f"🔔📉 BTC ROMPE MÍNIMO RELATIVO {scope_word} ANTERIOR",
        f"Precio actual: {current_price:,.0f} $",
        f"Mínimo relativo ({label}): {value:,.0f} $ ({pct:+.1f}%)",
    ])


def check_relative_levels(current_price):
    """
    Comprueba cada hora si el precio actual ha roto alguno de los
    maximos/minimos relativos que quedaron marcados al cortarse una racha
    (semanal o mensual). En cuanto se rompe, avisa y deja de vigilar ese
    nivel (ya cumplió su función).
    """
    data = read_watched_levels()
    changed = False

    for slot in ("weekly_max", "weekly_min", "monthly_max", "monthly_min"):
        level = data.get(slot)
        if not level or level.get("alerted"):
            continue

        broke = current_price > level["value"] if slot.endswith("_max") else current_price < level["value"]
        if broke:
            msg = build_relative_level_message(slot, current_price, level)
            print(f"AVISO (nivel relativo roto, {slot}):", msg)
            send_telegram(msg)
            data[slot] = None
            changed = True

    if changed:
        write_watched_levels(data)


def build_breakout_message(direction, current_price, ref_price, ref_key, scope):
    """
    direction: 'up' o 'down'. scope: 'weekly' o 'monthly'.
    Incluye la racha propia del plano (confirmada, sin contar el periodo en
    curso) y el contexto del otro plano temporal.
    """
    pct = ((current_price - ref_price) / ref_price) * 100 if ref_price else 0
    title = "MÁXIMO" if direction == "up" else "MÍNIMO"
    emoji = "📈" if direction == "up" else "📉"
    word = "Máximo" if direction == "up" else "Mínimo"

    if scope == "weekly":
        scope_word = "SEMANAL"
        ref_label = f"semana anterior ({week_key_to_label(ref_key)})"
        own_streak = describe_weekly_streak(direction)
        cross_streak = describe_monthly_streak(direction)
        own_label = "Racha semanal"
        cross_label = "Contexto mensual"
    else:
        scope_word = "MENSUAL"
        ref_label = f"mes anterior ({month_key_to_label(ref_key)})"
        own_streak = describe_monthly_streak(direction)
        cross_streak = describe_weekly_streak(direction)
        own_label = "Racha mensual"
        cross_label = "Contexto semanal"

    return "\n".join([
        f"🔔{emoji} BTC ROMPE {title} {scope_word}",
        f"Precio actual: {current_price:,.0f} $",
        f"{word} {ref_label}: {ref_price:,.0f} $ ({pct:+.1f}%)",
        f"📊 {own_label}: {own_streak}",
        "",
        f"📅 {cross_label}: {cross_streak}",
    ])


def check_weekly_breakout(current_price):
    """
    Comprueba si el precio actual ha roto el maximo o el minimo REAL
    (high/low intradiario de Twelve Data, no de cierre) de la ultima semana
    natural ya cerrada (lunes-domingo).

    Solo pide datos nuevos a Twelve Data cuando detecta que ha entrado una
    semana nueva (una vez por semana). En ese mismo instante confirma la
    racha de la semana que acaba de cerrarse (usando los flags acumulados
    durante esa semana) y, si corresponde, avisa del extremo relativo que
    deja una racha que se corta.
    """
    state = read_range_state(WEEKLY_RANGE_STATE_FILE)

    today = datetime.now(timezone.utc).date()
    current_year, current_week, _ = today.isocalendar()
    last_monday_this_week = datetime.fromisocalendar(current_year, current_week, 1).date()
    last_closed_week_end = last_monday_this_week - timedelta(days=1)
    last_closed_year, last_closed_week_num, _ = last_closed_week_end.isocalendar()
    last_closed_key = f"{last_closed_year}-W{last_closed_week_num:02d}"

    if state["key"] != last_closed_key:
        ohlc = get_btc_daily_ohlc_twelvedata(outputsize=14)
        new_key, new_high, new_low = compute_last_closed_week_range(ohlc)
        if new_key is None or new_high is None or new_low is None:
            print("Aviso: no se pudo calcular el rango real de la semana pasada, se omite la comprobación semanal esta hora")
            return

        if state["key"] is not None:
            confirm_weekly_streak(new_key, new_high, new_low, state["alerted_up"], state["alerted_down"])

        state = {"key": new_key, "high": new_high, "low": new_low, "alerted_up": False, "alerted_down": False}
        write_range_state(WEEKLY_RANGE_STATE_FILE, **state)
        print(f"Rango real semana pasada ({new_key}) actualizado: high={new_high:.0f}, low={new_low:.0f}")

    high, low, key = state["high"], state["low"], state["key"]
    if high is None or low is None:
        return

    if current_price > high and not state["alerted_up"]:
        msg = build_breakout_message("up", current_price, high, key, "weekly")
        print("AVISO (ruptura semanal, máximo):", msg)
        send_telegram(msg)
        state["alerted_up"] = True
        write_range_state(WEEKLY_RANGE_STATE_FILE, **state)
    elif current_price < low and not state["alerted_down"]:
        msg = build_breakout_message("down", current_price, low, key, "weekly")
        print("AVISO (ruptura semanal, mínimo):", msg)
        send_telegram(msg)
        state["alerted_down"] = True
        write_range_state(WEEKLY_RANGE_STATE_FILE, **state)


def check_monthly_breakout(current_price):
    """Igual que check_weekly_breakout pero con el mes natural ya cerrado."""
    state = read_range_state(MONTHLY_RANGE_STATE_FILE)

    today = datetime.now(timezone.utc).date()
    first_of_current_month = today.replace(day=1)
    last_closed_month_end = first_of_current_month - timedelta(days=1)
    last_closed_key = last_closed_month_end.strftime("%Y-%m")

    if state["key"] != last_closed_key:
        ohlc = get_btc_daily_ohlc_twelvedata(outputsize=45)
        new_key, new_high, new_low = compute_last_closed_month_range(ohlc)
        if new_key is None or new_high is None or new_low is None:
            print("Aviso: no se pudo calcular el rango real del mes pasado, se omite la comprobación mensual esta hora")
            return

        if state["key"] is not None:
            confirm_monthly_streak(new_key, new_high, new_low, state["alerted_up"], state["alerted_down"])

        state = {"key": new_key, "high": new_high, "low": new_low, "alerted_up": False, "alerted_down": False}
        write_range_state(MONTHLY_RANGE_STATE_FILE, **state)
        print(f"Rango real mes pasado ({new_key}) actualizado: high={new_high:.0f}, low={new_low:.0f}")

    high, low, key = state["high"], state["low"], state["key"]
    if high is None or low is None:
        return

    if current_price > high and not state["alerted_up"]:
        msg = build_breakout_message("up", current_price, high, key, "monthly")
        print("AVISO (ruptura mensual, máximo):", msg)
        send_telegram(msg)
        state["alerted_up"] = True
        write_range_state(MONTHLY_RANGE_STATE_FILE, **state)
    elif current_price < low and not state["alerted_down"]:
        msg = build_breakout_message("down", current_price, low, key, "monthly")
        print("AVISO (ruptura mensual, mínimo):", msg)
        send_telegram(msg)
        state["alerted_down"] = True
        write_range_state(MONTHLY_RANGE_STATE_FILE, **state)


def main():
    prices, volumes = get_market_chart(days=365)
    daily_closes = [p for _, p in prices]
    daily_volumes = [v for _, v in volumes]
    weekly_closes = group_last(prices, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))
    weekly_volumes = group_sum(volumes, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1]))

    check_weekly_breakout(daily_closes[-1])
    check_monthly_breakout(daily_closes[-1])
    check_relative_levels(daily_closes[-1])

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

    _, compra_items, venta_items, veto_compra, veto_venta = evaluate_strict_signal(
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
        "COMPRA", compra_items, state["tier_compra"], state["active_compra"], veto=veto_compra
    )
    tier_venta_now, active_venta_now = process_direction(
        "VENTA", venta_items, state["tier_venta"], state["active_venta"], veto=veto_venta
    )

    print(f"Nivel COMPRA actual: {tier_compra_now}/{len(compra_items)}")
    print(f"Nivel VENTA actual: {tier_venta_now}/{len(venta_items)}")

    write_last_state(tier_compra_now, tier_venta_now, active_compra_now, active_venta_now)


if __name__ == "__main__":
    main()
