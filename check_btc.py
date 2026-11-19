#!/usr/bin/env python3
import os
import json
import time
import smtplib
from email.mime.text import MIMEText
import urllib.error
import urllib.request
import urllib.parse

from report import get_market_chart

STATE_FILE = "last_threshold.txt"
SHARED_PRICE_FILE = "shared_price_history.json"
STEP = 1000
SHARED_HISTORY_DAYS = 15  # margen de sobra, price_move_alert.py necesita al menos 8


def current_threshold(price):
    return int(price // STEP) * STEP


def read_last_threshold():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return int(f.read().strip())
    return None


def write_last_threshold(value):
    with open(STATE_FILE, "w") as f:
        f.write(str(value))


def write_shared_price_history(daily_closes):
    """
    Guarda los ultimos dias de precio en un archivo compartido, para que
    price_move_alert.py no tenga que volver a llamar a la API de CoinGecko.
    """
    data = daily_closes[-SHARED_HISTORY_DAYS:]
    with open(SHARED_PRICE_FILE, "w") as f:
        json.dump(data, f)


def send_telegram(msg, retries=3):
    """
    Envia el mensaje a Telegram con reintentos. Un fallo puntual de red
    (timeout, 5xx, 429) ya no tumba el job a la primera: se reintenta con una
    pausa creciente. Un error permanente (token o chat_id mal, mensaje mal
    formado) no se reintenta porque fallaria igual. Si tras los reintentos
    sigue fallando, se lanza la excepcion como antes: el job falla, el
    escalon no se guarda y en la siguiente ejecucion se vuelve a intentar.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            urllib.request.urlopen(url, data=data, timeout=20)
            return
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            last_error = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
        print(f"Aviso: fallo al enviar a Telegram (intento {attempt}/{retries}): {last_error}")
        if attempt < retries:
            time.sleep(3 * attempt)
    raise last_error


def send_email(msg):
    user = os.environ.get("EMAIL_USER")
    pwd = os.environ.get("EMAIL_PASS")
    to = os.environ.get("EMAIL_TO", user)
    if not user or not pwd:
        return
    mail = MIMEText(msg)
    mail["Subject"] = "Alerta BTC"
    mail["From"] = user
    mail["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], mail.as_string())


def main():
    prices, _ = get_market_chart(days=365)
    daily_closes = [p for _, p in prices]
    price = daily_closes[-1]

    write_shared_price_history(daily_closes)

    threshold = current_threshold(price)
    last = read_last_threshold()

    print(f"Precio actual: {price} | Escalon actual: {threshold} | Ultimo notificado: {last}")

    if last is None:
        write_last_threshold(threshold)
        return

    if threshold != last:
        if threshold > last:
            msg = f"🟠 BTC 📈 a {threshold:,} $ (actual: {price:,.0f} $)"
        else:
            msg = f"🟠 BTC 📉 de {last:,} $ (actual: {price:,.0f} $)"
        print("AVISO:", msg)
        send_telegram(msg)
        # El email es secundario: si falla (Gmail, red) no debe impedir que
        # se guarde el escalon, porque Telegram ya ha salido y se duplicaria
        # el aviso en la siguiente ejecucion.
        try:
            send_email(msg)
        except Exception as e:
            print(f"Aviso: no se pudo enviar el email ({e})")
        write_last_threshold(threshold)


if __name__ == "__main__":
    main()
