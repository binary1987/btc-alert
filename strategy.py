#!/usr/bin/env python3
"""
Estrategia estricta de compra/venta.

Orden fijo de importancia (de mas a menos determinante):
  1. Distancia al STH Realized Price
  2. SMA200 diario
  3. RSI semanal
  4. MACD linea vs cero
  5. Fear & Greed
  6. SMA50 semanal
  7. RSI diario
  8. MACD histograma perdiendo fuerza

COMPRA: todas las condiciones se evaluan con umbrales de sobreventa/capitulacion.
VENTA: todas las condiciones se evaluan con umbrales de sobrecompra/euforia.
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
    Evalua las condiciones de COMPRA y de VENTA, en el orden fijo acordado.

    Devuelve (señal_o_None, compra_items, venta_items)
    donde cada *_items es una lista ordenada de tuplas:
        (texto_condicion, se_cumple_bool, valor_o_None, unidad_o_None)
    unidad es "%" para porcentajes, "" para numeros sin unidad (RSI, F&G),
    o None cuando esa condicion no muestra ningun valor (MACD).
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

    compra_items = [
        (
            "Distancia a STH Realized Price menor o igual a -10%",
            sth_pct_diff is not None and sth_pct_diff <= -10,
            sth_pct_diff, "%",
        ),
        (
            "SMA200 diario menor o igual a -20%",
            sma200_pct is not None and sma200_pct <= -20,
            sma200_pct, "%",
        ),
        (
            "RSI semanal menor o igual a 40",
            rsi_weekly is not None and rsi_weekly <= 40,
            rsi_weekly, "",
        ),
        (
            "MACD linea menor que 0",
            bool(len(macd_line) >= 1 and macd_line[-1] < 0),
            None, None,
        ),
        (
            "F&G menor o igual a 46",
            fng_value is not None and fng_value <= 46,
            fng_value, "",
        ),
        (
            "SMA50 semanal menor o igual a -20%",
            sma50w_pct is not None and sma50w_pct <= -20,
            sma50w_pct, "%",
        ),
        (
            "RSI diario menor o igual a 25",
            rsi_daily is not None and rsi_daily <= 25,
            rsi_daily, "",
        ),
        (
            "MACD rojo claro perdiendo fuerza",
            bool(len(macd_hist) >= 2 and macd_hist[-1] < 0 and weak),
            None, None,
        ),
    ]

    venta_items = [
        (
            "Distancia a STH Realized Price mayor o igual a +30%",
            sth_pct_diff is not None and sth_pct_diff >= 30,
            sth_pct_diff, "%",
        ),
        (
            "SMA200 diario mayor o igual a 60%",
            sma200_pct is not None and sma200_pct >= 60,
            sma200_pct, "%",
        ),
        (
            "RSI semanal mayor o igual a 60",
            rsi_weekly is not None and rsi_weekly >= 60,
            rsi_weekly, "",
        ),
        (
            "MACD linea mayor que 0",
            bool(len(macd_line) >= 1 and macd_line[-1] > 0),
            None, None,
        ),
        (
            "F&G mayor o igual a 55",
            fng_value is not None and fng_value >= 55,
            fng_value, "",
        ),
        (
            "SMA50 semanal mayor o igual a 50%",
            sma50w_pct is not None and sma50w_pct >= 50,
            sma50w_pct, "%",
        ),
        (
            "RSI diario mayor o igual a 75",
            rsi_daily is not None and rsi_daily >= 75,
            rsi_daily, "",
        ),
        (
            "MACD verde claro perdiendo fuerza",
            bool(len(macd_hist) >= 2 and macd_hist[-1] >= 0 and weak),
            None, None,
        ),
    ]

    compra_count = sum(1 for _, met, _, _ in compra_items if met)
    venta_count = sum(1 for _, met, _, _ in venta_items if met)

    signal = None
    if compra_count >= required:
        signal = "COMPRA"
    elif venta_count >= required:
        signal = "VENTA"

    return signal, compra_items, venta_items
