#!/usr/bin/env python3
"""
Estrategia estricta de compra/venta.

Orden fijo de importancia (de mas a menos determinante):
  1. Distancia al STH Realized Price (2 niveles: normal/fuerte)
  2. SMA200 diario (2 niveles: normal/fuerte)
  3. RSI semanal
  4. MACD linea vs cero
  5. Fear & Greed
  6. SMA50 semanal (2 niveles: normal/fuerte)
  7. RSI diario
  8. MACD histograma perdiendo fuerza

Las 3 condiciones de distancia (STH, SMA200, SMA50) puntuan 0, 1 o 2:
  0 = no cumple ni el umbral normal
  1 = cumple el umbral normal
  2 = cumple el umbral "fuerte" (zona historica mas extrema)

El resto de condiciones puntuan 0 o 1 (cumple / no cumple).
Puntuacion maxima total: 5*1 + 3*2 = 11 puntos.
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


def two_level_score(pct, normal_threshold, strong_threshold, greater_or_equal):
    """
    Puntua 0, 1 o 2 segun si pct supera el umbral normal y/o el fuerte.
    greater_or_equal=True para condiciones de venta (>=), False para compra (<=).
    Devuelve (puntos, es_fuerte).
    """
    if pct is None:
        return 0, False
    if greater_or_equal:
        if pct >= strong_threshold:
            return 2, True
        if pct >= normal_threshold:
            return 1, False
        return 0, False
    else:
        if pct <= strong_threshold:
            return 2, True
        if pct <= normal_threshold:
            return 1, False
        return 0, False


def evaluate_strict_signal(daily_closes, weekly_closes, fng_value, sth_realized_price=None, required=5):
    """
    Evalua las condiciones de COMPRA y de VENTA, en el orden fijo acordado.

    Devuelve (señal_o_None, compra_items, venta_items)
    donde cada *_items es una lista ordenada de tuplas:
        (texto_condicion, puntos, valor_o_None, unidad_o_None, es_fuerte)
    puntos es 0/1 para condiciones normales, o 0/1/2 para las de 2 niveles.
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

    # --- Puntuaciones de 2 niveles ---
    sth_compra_pts, sth_compra_strong = two_level_score(sth_pct_diff, -10, -20, greater_or_equal=False)
    sth_venta_pts, sth_venta_strong = two_level_score(sth_pct_diff, 30, 50, greater_or_equal=True)

    sma200_compra_pts, sma200_compra_strong = two_level_score(sma200_pct, -20, -30, greater_or_equal=False)
    sma200_venta_pts, sma200_venta_strong = two_level_score(sma200_pct, 40, 80, greater_or_equal=True)

    sma50_compra_pts, sma50_compra_strong = two_level_score(sma50w_pct, -20, -30, greater_or_equal=False)
    sma50_venta_pts, sma50_venta_strong = two_level_score(sma50w_pct, 50, 80, greater_or_equal=True)

    rsi_weekly_compra = 1 if (rsi_weekly is not None and rsi_weekly <= 40) else 0
    rsi_weekly_venta = 1 if (rsi_weekly is not None and rsi_weekly >= 60) else 0

    macd_line_compra = 1 if (len(macd_line) >= 1 and macd_line[-1] < 0) else 0
    macd_line_venta = 1 if (len(macd_line) >= 1 and macd_line[-1] > 0) else 0

    fng_compra = 1 if (fng_value is not None and fng_value <= 46) else 0
    fng_venta = 1 if (fng_value is not None and fng_value >= 55) else 0

    rsi_daily_compra = 1 if (rsi_daily is not None and rsi_daily <= 25) else 0
    rsi_daily_venta = 1 if (rsi_daily is not None and rsi_daily >= 75) else 0

    macd_hist_compra = 1 if (len(macd_hist) >= 2 and macd_hist[-1] < 0 and weak) else 0
    macd_hist_venta = 1 if (len(macd_hist) >= 2 and macd_hist[-1] >= 0 and weak) else 0

    compra_items = [
        ("Distancia a STH Realized Price menor o igual a -10%", sth_compra_pts, sth_pct_diff, "%", sth_compra_strong),
        ("SMA200 diario menor o igual a -20%", sma200_compra_pts, sma200_pct, "%", sma200_compra_strong),
        ("RSI semanal menor o igual a 40", rsi_weekly_compra, rsi_weekly, "", False),
        ("MACD linea menor que 0", macd_line_compra, None, None, False),
        ("F&G menor o igual a 46", fng_compra, fng_value, "", False),
        ("SMA50 semanal menor o igual a -20%", sma50_compra_pts, sma50w_pct, "%", sma50_compra_strong),
        ("RSI diario menor o igual a 25", rsi_daily_compra, rsi_daily, "", False),
        ("MACD rojo claro perdiendo fuerza", macd_hist_compra, None, None, False),
    ]

    venta_items = [
        ("Distancia a STH Realized Price mayor o igual a +30%", sth_venta_pts, sth_pct_diff, "%", sth_venta_strong),
        ("SMA200 diario mayor o igual a 40%", sma200_venta_pts, sma200_pct, "%", sma200_venta_strong),
        ("RSI semanal mayor o igual a 60", rsi_weekly_venta, rsi_weekly, "", False),
        ("MACD linea mayor que 0", macd_line_venta, None, None, False),
        ("F&G mayor o igual a 55", fng_venta, fng_value, "", False),
        ("SMA50 semanal mayor o igual a 50%", sma50_venta_pts, sma50w_pct, "%", sma50_venta_strong),
        ("RSI diario mayor o igual a 75", rsi_daily_venta, rsi_daily, "", False),
        ("MACD verde claro perdiendo fuerza", macd_hist_venta, None, None, False),
    ]

    # Conteo de "condiciones activas" (>=1 punto), igual que el sistema anterior de X/8
    compra_conditions_met = sum(1 for _, pts, _, _, _ in compra_items if pts >= 1)
    venta_conditions_met = sum(1 for _, pts, _, _, _ in venta_items if pts >= 1)

    signal = None
    if compra_conditions_met >= required:
        signal = "COMPRA"
    elif venta_conditions_met >= required:
        signal = "VENTA"

    return signal, compra_items, venta_items
