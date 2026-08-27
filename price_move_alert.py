#!/usr/bin/env python3
"""
Alerta de movimiento de precio (% diario y % semanal), con dos niveles:
normal y fuerte. A partir del primer aviso, vuelve a avisar cada vez que
el movimiento aumenta 1 punto porcentual o mas respecto al ultimo aviso,
y marca claramente cuando el movimiento pasa de "normal" a "fuerte".
El contador se reinicia al empezar un dia/semana nuevo.

IMPORTANTE: no llama a la API de CoinGecko. Lee el historico de precios
que ya guarda check_btc.py en shared_price_history.json, para poder correr
con la misma frecuencia (cada 10 min) sin coste extra de API. Por eso el
cronjob de este script debe programarse unos minutos DESPUES del de
check_btc.py, para asegurarse de que el archivo compartido esta actualizado.
"""
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

from report import compute_roc

STATE_FILE = "last_price_move.txt"
SHARED_PRICE_FILE = "shared_price_history.json"

DAILY_NORMAL = 5
DAILY_STRONG = 10
WEEKLY_NORMAL = 12
WEEKLY_STRONG = 20

INCREMENT_STEP = 1  # puntos porcentuales de aumento para volver a avisar


def read_shared_price_history():
    """Devuelve la lista de precios guardada por check_btc.py, o None si no existe todavia."""
    if not os.path.exists(SHARED_PRICE_FILE):
        return None
    with open(SHARED_PRICE_FILE) as f:
        return json.load(f)


def default_state():
    return {
        "day": None, "day_up": None, "day_down": None,
        "week": None, "week_up": None, "week_down": None,
    }


def read_state():
    default = default_state()
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


def write_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


def build_message(period_label, pct, prev_pct, is_strong_now, was_strong_before,
                   current_price, past_price, past_label):
    direction_emoji = "📈" if pct >= 0 else "📉"
    direction_word = "de subida" if pct >= 0 else "de bajada"
    is_first = prev_pct is None
    just_became_strong = is_strong_now and not was_strong_before and not is_first

    if is_first:
        strong_tag = "🔥" if is_strong_now else ""
        strong_word = " FUERTE" if is_strong_now else ""
        line1 = f"🔔{direction_emoji}{strong_tag} Movimiento {period_label} {direction_word}{strong_word}: {pct:+.1f}%"
    elif just_became_strong:
        line1 = (
            f"🔔{direction_emoji}🔥 Movimiento {period_label} {direction_word} pasa a FUERTE: "
            f"{pct:+.1f}% (antes {prev_pct:+.1f}%)"
        )
    else:
        strong_tag = "🔥" if is_strong_now else ""
        line1 = (
            f"🔔{direction_emoji}{strong_tag} Movimiento {period_label} {direction_word} continúa: "
            f"{pct:+.1f}% (antes {prev_pct:+.1f}%)"
        )

    line2 = f"Precio actual: {current_price:,.0f} $ ({past_label}: {past_price:,.0f} $)"
    return f"{line1}\n{line2}"


def process_period(pct, normal_th, strong_th, last_up, last_down):
    """
    Evalua un periodo (dia o semana). Devuelve (debe_avisar, prev_pct,
    is_strong_now, was_strong_before, nuevo_last_up, nuevo_last_down).
    """
    new_last_up = last_up
    new_last_down = last_down

    if pct is None:
        return False, None, False, False, new_last_up, new_last_down

    magnitude = abs(pct)
    is_strong_now = magnitude >= strong_th

    if pct >= 0:
        last = last_up
    else:
        last = last_down

    should_alert = False
    prev_pct_signed = None
    was_strong_before = False

    if magnitude >= normal_th:
        if last is None:
            should_alert = True
        elif magnitude >= last + INCREMENT_STEP:
            should_alert = True

        if should_alert:
            if last is not None:
                prev_pct_signed = last if pct >= 0 else -last
                was_strong_before = last >= strong_th
            if pct >= 0:
                new_last_up = magnitude
            else:
                new_last_down = magnitude

    return should_alert, prev_pct_signed, is_strong_now, was_strong_before, new_last_up, new_last_down


def main():
    daily_closes = read_shared_price_history()

    if not daily_closes or len(daily_closes) < 8:
        print("Aviso: historico compartido todavia insuficiente (necesita al menos 8 dias). Se sale sin comprobar.")
        return

    current_price = daily_closes[-1]

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
    week_str = f"{iso_year}-W{iso_week:02d}"

    state = read_state()

    # Reiniciar contadores si ha empezado un dia/semana nuevo
    day_up, day_down = state["day_up"], state["day_down"]
    if state["day"] != today_str:
        day_up, day_down = None, None

    week_up, week_down = state["week_up"], state["week_down"]
    if state["week"] != week_str:
        week_up, week_down = None, None

    daily_pct = compute_roc(daily_closes, 1)
    weekly_pct = compute_roc(daily_closes, 7)

    print(f"Movimiento diario: {daily_pct} | ultimo up/down guardados: {day_up}/{day_down}")
    print(f"Movimiento semanal: {weekly_pct} | ultimo up/down guardados: {week_up}/{week_down}")

    # --- Diario ---
    should_alert, prev_pct, is_strong_now, was_strong_before, day_up, day_down = process_period(
        daily_pct, DAILY_NORMAL, DAILY_STRONG, day_up, day_down
    )
    if should_alert:
        past_price = daily_closes[-2]
        msg = build_message("diario", daily_pct, prev_pct, is_strong_now, was_strong_before,
                             current_price, past_price, "ayer")
        print("AVISO (diario):", msg)
        send_telegram(msg)

    # --- Semanal ---
    should_alert, prev_pct, is_strong_now, was_strong_before, week_up, week_down = process_period(
        weekly_pct, WEEKLY_NORMAL, WEEKLY_STRONG, week_up, week_down
    )
    if should_alert:
        past_price = daily_closes[-8]
        msg = build_message("semanal", weekly_pct, prev_pct, is_strong_now, was_strong_before,
                             current_price, past_price, "hace 7 días")
        print("AVISO (semanal):", msg)
        send_telegram(msg)

    new_state = {
        "day": today_str, "day_up": day_up, "day_down": day_down,
        "week": week_str, "week_up": week_up, "week_down": week_down,
    }
    write_state(new_state)


if __name__ == "__main__":
    main()
