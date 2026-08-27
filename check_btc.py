#!/usr/bin/env python3
import os
import json
import smtplib
from email.mime.text import MIMEText
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


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode()
    urllib.request.urlopen(url, data=data, timeout=10)


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
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
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
            msg = f"🟠 BTC subió a {threshold:,} $ (actual: {price:,.0f} $)"
        else:
            msg = f"🟠 BTC bajó de {last:,} $ (actual: {price:,.0f} $)"
        print("AVISO:", msg)
        send_telegram(msg)
        send_email(msg)
        write_last_threshold(threshold)


if __name__ == "__main__":
    main()
