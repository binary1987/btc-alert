#!/usr/bin/env python3
"""
Alerta de movimiento de precio (% diario y % semanal), con dos niveles:
normal y fuerte. Avisa una sola vez por dia (diario) o por semana (semanal),
reseteando el aviso al empezar el periodo siguiente.

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
WEEKLY_STRONG = 24


def read_shared_price_history():
    """Devuelve la lista de precios guardada por check_btc.py, o None si no existe todavia."""
    if not os.path.exists(SHARED_PRICE_FILE):
        return None
    with open(SHARED_PRICE_FILE) as f:
        return json.load(f)


def read_state():
    """Devuelve {'day': str_o_None, 'week': str_o_None} con el ultimo periodo ya avisado."""
    default = {"day": None, "week": None}
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


def write_state(day, week):
    with open(STATE_FILE, "w") as f:
        json.dump({"day": day, "week": week}, f)


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


def build_message(period_label, pct, is_strong, current_price, past_price, past_label):
    direction_emoji = "📈" if pct >= 0 else "📉"
    strong_tag = "🔥" if is_strong else ""
    strong_word = " FUERTE" if is_strong else ""

    line1 = f"🔔{direction_emoji}{strong_tag} Movimiento {period_label}{strong_word}: {pct:+.1f}%"
    line2 = f"Precio actual: {current_price:,.0f} $ ({past_label}: {past_price:,.0f} $)"
    return f"{line1}\n{line2}"


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
    print(f"Dia ya avisado: {state['day']} | Semana ya avisada: {state['week']}")
    print(f"Dia actual: {today_str} | Semana actual: {week_str}")

    daily_pct = compute_roc(daily_closes, 1)
    weekly_pct = compute_roc(daily_closes, 7)

    print(f"Movimiento diario: {daily_pct}")
    print(f"Movimiento semanal: {weekly_pct}")

    new_day_state = state["day"]
    new_week_state = state["week"]

    # --- Movimiento diario ---
    if state["day"] != today_str and daily_pct is not None and abs(daily_pct) >= DAILY_NORMAL:
        is_strong = abs(daily_pct) >= DAILY_STRONG
        past_price = daily_closes[-2]
        msg = build_message("diario", daily_pct, is_strong, current_price, past_price, "ayer")
        print("AVISO (diario):", msg)
        send_telegram(msg)
        new_day_state = today_str
    elif state["day"] != today_str:
        new_day_state = None

    # --- Movimiento semanal ---
    if state["week"] != week_str and weekly_pct is not None and abs(weekly_pct) >= WEEKLY_NORMAL:
        is_strong = abs(weekly_pct) >= WEEKLY_STRONG
        past_price = daily_closes[-8]
        msg = build_message("semanal", weekly_pct, is_strong, current_price, past_price, "hace 7 días")
        print("AVISO (semanal):", msg)
        send_telegram(msg)
        new_week_state = week_str
    elif state["week"] != week_str:
        new_week_state = None

    write_state(new_day_state, new_week_state)


if __name__ == "__main__":
    main()
