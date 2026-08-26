#!/usr/bin/env python3
"""
Estrategia estricta de compra/venta definida por el usuario.

COMPRA (todas las condiciones deben cumplirse):
  - RSI diario (14) <= 25
  - RSI semanal (14) <= 40
  - MACD histograma en rojo Y perdiendo fuerza (rojo claro)
  - Linea MACD por debajo de 0
  - Fear & Greed <= 46
  - Precio al menos 10% por debajo del STH Realized Price (sobreventa on-chain)

VENTA (todas las condiciones deben cumplirse):
  - RSI diario (14) >= 75
  - RSI semanal (14) >= 60
  - MACD histograma en verde Y perdiendo fuerza (verde claro)
  - Linea MACD por encima de 0
  - Fear & Greed >= 55
  - Precio al menos 10% por encima del STH Realized Price (sobrecompra on-chain)
"""
from report import compute_rsi, compute_macd_histogram, ema_series


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
    Devuelve (señal_o_None, condiciones_compra, condiciones_venta)
    condiciones_* son diccionarios {texto: True/False}
    """
    rsi_daily = compute_rsi(daily_closes)
    rsi_weekly = compute_rsi(weekly_closes)
    macd_hist = compute_macd_histogram(daily_closes)
    macd_line = compute_macd_line(daily_closes)
    weak = macd_weakening(macd_hist)
    current_price = daily_closes[-1]

    sth_lower_band = sth_realized_price * 0.90 if sth_realized_price is not None else None
    sth_upper_band = sth_realized_price * 1.10 if sth_realized_price is not None else None

    conditions_compra = {
        "RSI diario <= 25": rsi_daily is not None and rsi_daily <= 25,
        "RSI semanal <= 40": rsi_weekly is not None and rsi_weekly <= 40,
        "MACD hist rojo perdiendo fuerza": bool(
            len(macd_hist) >= 2 and macd_hist[-1] < 0 and weak
        ),
        "MACD linea < 0": bool(len(macd_line) >= 1 and macd_line[-1] < 0),
        "F&G <= 46": fng_value is not None and fng_value <= 46,
        "Precio 10% bajo STH Realized Price": (
            sth_lower_band is not None and current_price < sth_lower_band
        ),
    }

    conditions_venta = {
        "RSI diario >= 75": rsi_daily is not None and rsi_daily >= 75,
        "RSI semanal >= 60": rsi_weekly is not None and rsi_weekly >= 60,
        "MACD hist verde perdiendo fuerza": bool(
            len(macd_hist) >= 2 and macd_hist[-1] >= 0 and weak
        ),
        "MACD linea > 0": bool(len(macd_line) >= 1 and macd_line[-1] > 0),
        "F&G >= 55": fng_value is not None and fng_value >= 55,
        "Precio 10% sobre STH Realized Price": (
            sth_upper_band is not None and current_price > sth_upper_band
        ),
    }

    compra_count = sum(conditions_compra.values())
    venta_count = sum(conditions_venta.values())

    signal = None
    if compra_count >= required:
        signal = "COMPRA"
    elif venta_count >= required:
        signal = "VENTA"

    return signal, conditions_compra, conditions_venta
