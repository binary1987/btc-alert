#!/usr/bin/env python3
import os
import json
import smtplib
from email.mime.text import MIMEText
import urllib.request
import urllib.parse

STATE_FILE = "last_threshold.txt"
STEP = 1000

def get_btc_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode())
    return data["bitcoin"]["usd"]

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
    price = get_btc_price()
    threshold = current_threshold(price)
    last = read_last_threshold()

    print(f"Precio actual: {price} | Escalon actual: {threshold} | Ultimo notificado: {last}")

    if last is None:
        write_last_threshold(threshold)
        return

    if threshold != last:
        direction = "subido" if threshold > last else "bajado"
        announced_level = last if direction == "bajado" else threshold
        msg = f"BTC ha {direction} y ha cruzado los {announced_level:,} $ (precio actual: {price:,.0f} $)"
        print("AVISO:", msg)
        send_telegram(msg)
        send_email(msg)
        write_last_threshold(threshold)

if __name__ == "__main__":
    main()
