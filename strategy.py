#!/usr/bin/env python3
"""
Estrategia estricta de compra/venta definida por el usuario.

COMPRA (todas las condiciones deben cumplirse):
  - RSI diario (14) <= 25
  - RSI semanal (14) <= 40
  - MACD histograma en rojo Y perdiendo fuerza (rojo claro)
  - Linea MACD por debajo de 0
  - Fear & Greed <= 46
  - Precio 10% por debajo del STH Realized Price
  - SMA200 diario <= -20%
  - SMA50 semanal <= -20%

VENTA (todas las condiciones deben cumplirse):
  - RSI diario (14) >= 75
  - RSI semanal (14) >= 60
  - MACD histograma en verde Y perdiendo fuerza (verde claro)
  - Linea MACD por encima de 0
  - Fear & Greed >= 55
  - Precio 30% por encima del STH Realized Price
  - SMA200 diario >= 60%
  - SMA50 semanal >= 50%
"""
from report import compute_rsi, compute_macd_histogram, ema_series, compute_sma


def compute_macd_line(closes):
    """Devuelve la serie de la linea MACD (EMA12 - EMA26), alineada con el histograma."""
    ema12_full = ema_series(closes, 12)
    ema26_full = ema_series(closes, 26)
    if not ema12_full or not ema26_full:
        return []

    offset = len(ema12_full) - len(ema26_full)
    ema12_aligned = ema12_full[offset:]
    macd_line = [a - b for a, b in zip(ema12_aligned, ema26_full)]

    signal_line = ema_series(macd_line, 9)
    if not signal_line:
        return []

    macd_aligned = macd_line[len(macd_line) - len(signal_line):]
    return macd_aligned


def macd_weakening(histogram):
    """True si el histograma de hoy tiene menor valor absoluto que el de ayer (pierde fuerza)."""
    if len(histogram) < 2:
        return None
    return abs(histogram[-1]) < abs(histogram[-2])


def evaluate_strict_signal(daily_closes, weekly_closes, fng_value, sth_realized_price=None, required=5):
    """
    Evalua las condiciones de COMPRA y de VENTA.
    Devuelve (señal_o_None, condiciones_compra, condiciones_venta, pct_map)
    condiciones_* son diccionarios {texto: True/False}
    pct_map es un diccionario {texto_condicion: valor_%} para las condiciones
    basadas en distancia porcentual, util para mostrar el dato real en el mensaje.
    """
    rsi_daily = compute_rsi(daily_closes)
    rsi_weekly = compute_rsi(weekly_closes)
    macd_hist = compute_macd_histogram(daily_closes)
    macd_line = compute_macd_line(daily_closes)
    weak = macd_weakening(macd_hist)
    current_price = daily_closes[-1]

    sth_pct_diff = None
    if sth_realized_price is not None and sth_realized_price != 0:
        sth_pct_diff = ((current_price - sth_realized_price) / sth_realized_price) * 100

    sma200_daily = compute_sma(daily_closes, 200)
    sma200_pct = None
    if sma200_daily:
        sma200_pct = ((current_price - sma200_daily) / sma200_daily) * 100

    sma50_weekly = compute_sma(weekly_closes, 50)
    sma50w_pct = None
    if sma50_weekly:
        sma50w_pct = ((current_price - sma50_weekly) / sma50_weekly) * 100

    conditions_compra = {
        "RSI diario <= 25": rsi_daily is not None and rsi_daily <= 25,
        "RSI semanal <= 40": rsi_weekly is not None and rsi_weekly <= 40,
        "MACD rojo claro perdiendo fuerza": bool(
            len(macd_hist) >= 2 and macd_hist[-1] < 0 and weak
        ),
        "MACD linea < 0": bool(len(macd_line) >= 1 and macd_line[-1] < 0),
        "F&G <= 46": fng_value is not None and fng_value <= 46,
        "Precio 10% por debajo de STH Realized Price": (
            sth_pct_diff is not None and sth_pct_diff <= -10
        ),
        "SMA200 diario <= -20%": sma200_pct is not None and sma200_pct <= -20,
        "SMA50 semanal <= -20%": sma50w_pct is not None and sma50w_pct <= -20,
    }

    conditions_venta = {
        "RSI diario >= 75": rsi_daily is not None and rsi_daily >= 75,
        "RSI semanal >= 60": rsi_weekly is not None and rsi_weekly >= 60,
        "MACD verde claro perdiendo fuerza": bool(
            len(macd_hist) >= 2 and macd_hist[-1] >= 0 and weak
        ),
        "MACD linea > 0": bool(len(macd_line) >= 1 and macd_line[-1] > 0),
        "F&G >= 55": fng_value is not None and fng_value >= 55,
        "Precio 30% por encima de STH Realized Price": (
            sth_pct_diff is not None and sth_pct_diff >= 30
        ),
        "SMA200 diario >= 60%": sma200_pct is not None and sma200_pct >= 60,
        "SMA50 semanal >= 50%": sma50w_pct is not None and sma50w_pct >= 50,
    }

    compra_count = sum(conditions_compra.values())
    venta_count = sum(conditions_venta.values())

    signal = None
    if compra_count >= required:
        signal = "COMPRA"
    elif venta_count >= required:
        signal = "VENTA"

    pct_map = {
        "Precio 10% por debajo de STH Realized Price": sth_pct_diff,
        "Precio 30% por encima de STH Realized Price": sth_pct_diff,
        "SMA200 diario <= -20%": sma200_pct,
        "SMA200 diario >= 60%": sma200_pct,
        "SMA50 semanal <= -20%": sma50w_pct,
        "SMA50 semanal >= 50%": sma50w_pct,
    }

    return signal, conditions_compra, conditions_venta, pct_map
