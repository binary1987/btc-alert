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
  9. Divergencia diaria (RSI)
  10. Divergencia semanal (RSI)
  11. Divergencia SMA200 diario
  12. Divergencia SMA50 semanal
  13. Divergencia STH Realized Price
  14. Bollinger diario (tocando banda superior/inferior)
  15. Bollinger semanal (tocando banda superior/inferior)
  16. SMA200 semanal (fuente: Twelve Data, histórico mayor a 365 días)
  17. Divergencia SMA200 semanal
  18. RSI diario y semanal combinados (ambos en la misma zona extrema a la vez)
  19. MACD línea semanal vs cero
  20. MACD histograma semanal perdiendo fuerza
  21. Pico de volumen diario (>=2.5x la media de 30 dias)
  22. Pico de volumen semanal (>=1.8x la media de 12 semanas)

Todas las condiciones puntuan 0 o 1 (cumple / no cumple).
La "fuerza" de una señal de distancia (STH/SMA200/SMA50) ya no se mide con
un segundo umbral de porcentaje: se mide con su condicion de divergencia
correspondiente, que es independiente del umbral de %. Esto evita el problema
de que los picos tardios de un ciclo tengan % menores aunque el precio sea
mas extremo (rendimientos decrecientes).

Los picos de volumen siguen la misma logica "contraria" que el resto: un
pico a la baja (mucha venta) se interpreta como posible capitulacion ->
compra; un pico al alza (mucha compra) como posible euforia -> venta.

VETO DE CONTEXTO: con 22 condiciones, algunas de bajo peso pueden alinearse
por casualidad y activar una zona que contradice lo que dicen los
indicadores mas fiables (RSI diario y Fear & Greed). Para evitarlo:
  - Zona de COMPRA se BLOQUEA si RSI diario >= 60 Y F&G >= 60 a la vez
    (mercado caro + codicia, contradice comprar).
  - Zona de VENTA se BLOQUEA si RSI diario <= 40 Y F&G <= 40 a la vez
    (mercado barato + miedo, contradice vender).
El veto no altera el conteo de condiciones (compra_conditions_met /
venta_conditions_met), solo se devuelve aparte para que quien reciba el
resultado decida no avisar, aunque el nivel siga contando internamente.

Puntuacion maxima total: 22 puntos.
"""
from report import (
    compute_rsi, compute_macd_histogram, ema_series, compute_sma,
    detect_divergence, detect_sma_divergence,
    compute_bollinger, bollinger_signal, detect_volume_spike,
)


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


def evaluate_strict_signal(daily_closes, weekly_closes, fng_value,
                            sth_realized_price=None, sth_divergence="sin datos suficientes",
                            sma200w_pct=None, div_sma200w="sin datos suficientes",
                            daily_volumes=None, weekly_volumes=None,
                            required=5):
    """
    Evalua las condiciones de COMPRA y de VENTA, en el orden fijo acordado.

    sma200w_pct: distancia % del precio actual a la SMA200 SEMANAL, ya
    calculada fuera de esta funcion (necesita un historico de precios de
    Twelve Data, no de los daily_closes/weekly_closes de CoinGecko, que
    solo cubren 365 dias y no bastan para 200 semanas).
    div_sma200w: divergencia de esa misma SMA200 semanal, tambien
    precalculada fuera.

    Devuelve (señal_o_None, compra_items, venta_items, veto_compra, veto_venta)
    donde cada *_items es una lista ordenada de tuplas:
        (texto_condicion, puntos, valor_o_None, unidad_o_None)
    puntos es 0 o 1. unidad es "%" para porcentajes, "" para numeros sin
    unidad (RSI, F&G), o None cuando esa condicion no muestra valor (MACD,
    divergencias).
    """
    rsi_daily = compute_rsi(daily_closes)
    rsi_weekly = compute_rsi(weekly_closes)
    macd_hist = compute_macd_histogram(daily_closes)
    macd_line = compute_macd_line(daily_closes)
    weak = macd_weakening(macd_hist)
    macd_weekly_hist = compute_macd_histogram(weekly_closes)
    macd_weekly_line = compute_macd_line(weekly_closes)
    weak_weekly = macd_weakening(macd_weekly_hist)
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

    # --- Condiciones de magnitud (umbral unico, sin nivel "fuerte") ---
    sth_compra = 1 if (sth_pct_diff is not None and sth_pct_diff <= -10) else 0
    sth_venta = 1 if (sth_pct_diff is not None and sth_pct_diff >= 30) else 0

    sma200_compra = 1 if (sma200_pct is not None and sma200_pct <= -25) else 0
    sma200_venta = 1 if (sma200_pct is not None and sma200_pct >= 45) else 0

    sma50_compra = 1 if (sma50w_pct is not None and sma50w_pct <= -20) else 0
    sma50_venta = 1 if (sma50w_pct is not None and sma50w_pct >= 60) else 0

    sma200w_compra = 1 if (sma200w_pct is not None and sma200w_pct <= -5) else 0
    sma200w_venta = 1 if (sma200w_pct is not None and sma200w_pct >= 100) else 0

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

    macd_line_weekly_compra = 1 if (len(macd_weekly_line) >= 1 and macd_weekly_line[-1] < 0) else 0
    macd_line_weekly_venta = 1 if (len(macd_weekly_line) >= 1 and macd_weekly_line[-1] > 0) else 0

    macd_hist_weekly_compra = 1 if (len(macd_weekly_hist) >= 2 and macd_weekly_hist[-1] < 0 and weak_weekly) else 0
    macd_hist_weekly_venta = 1 if (len(macd_weekly_hist) >= 2 and macd_weekly_hist[-1] >= 0 and weak_weekly) else 0

    # RSI diario y semanal combinados: ambos en zona extrema a la vez
    # (reutiliza los mismos umbrales de rsi_daily_compra/venta y
    # rsi_weekly_compra/venta, que ya son 25/75 diario y 40/60 semanal)
    rsi_combo_compra = 1 if (rsi_daily_compra and rsi_weekly_compra) else 0
    rsi_combo_venta = 1 if (rsi_daily_venta and rsi_weekly_venta) else 0

    # Picos de volumen: logica "contraria" (pico a la baja = compra, pico
    # al alza = venta). Umbrales distintos porque el volumen diario es mas
    # ruidoso que el semanal (que ya viene suavizado al ser una suma).
    vol_spike_daily = None
    if daily_volumes:
        vol_spike_daily = detect_volume_spike(daily_closes, daily_volumes, avg_period=30, multiplier=2.5)

    vol_spike_weekly = None
    if weekly_volumes:
        vol_spike_weekly = detect_volume_spike(weekly_closes, weekly_volumes, avg_period=12, multiplier=1.8)

    vol_daily_compra = 1 if vol_spike_daily == "bajista" else 0
    vol_daily_venta = 1 if vol_spike_daily == "alcista" else 0

    vol_weekly_compra = 1 if vol_spike_weekly == "bajista" else 0
    vol_weekly_venta = 1 if vol_spike_weekly == "alcista" else 0

    # --- Condiciones de divergencia (independientes del umbral de %) ---
    div_daily = detect_divergence(daily_closes, order=3, min_distance=5)
    div_weekly = detect_divergence(weekly_closes, order=2, min_distance=3)
    div_sma200 = detect_sma_divergence(daily_closes, period=200, order=3, min_distance=5)
    div_sma50w = detect_sma_divergence(weekly_closes, period=50, order=2, min_distance=3)

    div_daily_compra = 1 if "alcista" in div_daily else 0
    div_daily_venta = 1 if "bajista" in div_daily else 0

    div_weekly_compra = 1 if "alcista" in div_weekly else 0
    div_weekly_venta = 1 if "bajista" in div_weekly else 0

    div_sma200_compra = 1 if "alcista" in div_sma200 else 0
    div_sma200_venta = 1 if "bajista" in div_sma200 else 0

    div_sma50w_compra = 1 if "alcista" in div_sma50w else 0
    div_sma50w_venta = 1 if "bajista" in div_sma50w else 0

    div_sth_compra = 1 if "alcista" in sth_divergence else 0
    div_sth_venta = 1 if "bajista" in sth_divergence else 0

    div_sma200w_compra = 1 if "alcista" in div_sma200w else 0
    div_sma200w_venta = 1 if "bajista" in div_sma200w else 0

    boll_daily = compute_bollinger(daily_closes)
    boll_sig = bollinger_signal(boll_daily)
    boll_compra = 1 if boll_sig == "sobreventa" else 0
    boll_venta = 1 if boll_sig == "sobrecompra" else 0

    boll_weekly = compute_bollinger(weekly_closes)
    boll_weekly_sig = bollinger_signal(boll_weekly)
    boll_weekly_compra = 1 if boll_weekly_sig == "sobreventa" else 0
    boll_weekly_venta = 1 if boll_weekly_sig == "sobrecompra" else 0

    compra_items = [
        ("Distancia a STH Realized Price menor o igual a -10%", sth_compra, sth_pct_diff, "%"),
        ("SMA200 diario menor o igual a -25%", sma200_compra, sma200_pct, "%"),
        ("RSI semanal menor o igual a 40", rsi_weekly_compra, rsi_weekly, ""),
        ("MACD línea diario menor que 0", macd_line_compra, None, None),
        ("F&G menor o igual a 46", fng_compra, fng_value, ""),
        ("SMA50 semanal menor o igual a -20%", sma50_compra, sma50w_pct, "%"),
        ("RSI diario menor o igual a 25", rsi_daily_compra, rsi_daily, ""),
        ("MACD histograma diario rojo perdiendo fuerza", macd_hist_compra, None, None),
        ("Divergencia RSI diario alcista", div_daily_compra, None, None),
        ("Divergencia RSI semanal alcista", div_weekly_compra, None, None),
        ("Divergencia SMA200 diario alcista", div_sma200_compra, None, None),
        ("Divergencia SMA50 semanal alcista", div_sma50w_compra, None, None),
        ("Divergencia STH Realized Price alcista", div_sth_compra, None, None),
        ("Bollinger diario tocando banda inferior", boll_compra, None, None),
        ("Bollinger semanal tocando banda inferior", boll_weekly_compra, None, None),
        ("SMA200 semanal menor o igual a -5%", sma200w_compra, sma200w_pct, "%"),
        ("Divergencia SMA200 semanal alcista", div_sma200w_compra, None, None),
        ("RSI diario y semanal combinados en sobreventa", rsi_combo_compra, None, None),
        ("MACD línea semanal menor que 0", macd_line_weekly_compra, None, None),
        ("MACD histograma semanal rojo perdiendo fuerza", macd_hist_weekly_compra, None, None),
        ("Pico de volumen diario a la baja (posible capitulación)", vol_daily_compra, None, None),
        ("Pico de volumen semanal a la baja (posible capitulación)", vol_weekly_compra, None, None),
    ]

    venta_items = [
        ("Distancia a STH Realized Price mayor o igual a +30%", sth_venta, sth_pct_diff, "%"),
        ("SMA200 diario mayor o igual a 45%", sma200_venta, sma200_pct, "%"),
        ("RSI semanal mayor o igual a 60", rsi_weekly_venta, rsi_weekly, ""),
        ("MACD línea diario mayor que 0", macd_line_venta, None, None),
        ("F&G mayor o igual a 55", fng_venta, fng_value, ""),
        ("SMA50 semanal mayor o igual a 60%", sma50_venta, sma50w_pct, "%"),
        ("RSI diario mayor o igual a 75", rsi_daily_venta, rsi_daily, ""),
        ("MACD histograma diario verde perdiendo fuerza", macd_hist_venta, None, None),
        ("Divergencia RSI diario bajista", div_daily_venta, None, None),
        ("Divergencia RSI semanal bajista", div_weekly_venta, None, None),
        ("Divergencia SMA200 diario bajista", div_sma200_venta, None, None),
        ("Divergencia SMA50 semanal bajista", div_sma50w_venta, None, None),
        ("Divergencia STH Realized Price bajista", div_sth_venta, None, None),
        ("Bollinger diario tocando banda superior", boll_venta, None, None),
        ("Bollinger semanal tocando banda superior", boll_weekly_venta, None, None),
        ("SMA200 semanal mayor o igual a 100%", sma200w_venta, sma200w_pct, "%"),
        ("Divergencia SMA200 semanal bajista", div_sma200w_venta, None, None),
        ("RSI diario y semanal combinados en sobrecompra", rsi_combo_venta, None, None),
        ("MACD línea semanal mayor que 0", macd_line_weekly_venta, None, None),
        ("MACD histograma semanal verde perdiendo fuerza", macd_hist_weekly_venta, None, None),
        ("Pico de volumen diario al alza (posible euforia)", vol_daily_venta, None, None),
        ("Pico de volumen semanal al alza (posible euforia)", vol_weekly_venta, None, None),
    ]

    compra_conditions_met = sum(1 for _, pts, _, _ in compra_items if pts >= 1)
    venta_conditions_met = sum(1 for _, pts, _, _ in venta_items if pts >= 1)

    # Veto de contexto: bloquea el aviso si los indicadores mas fiables
    # (RSI diario + F&G) contradicen abiertamente la zona activada.
    veto_compra = bool(rsi_daily is not None and fng_value is not None
                        and rsi_daily >= 60 and fng_value >= 60)
    veto_venta = bool(rsi_daily is not None and fng_value is not None
                       and rsi_daily <= 40 and fng_value <= 40)

    signal = None
    if compra_conditions_met >= required and not veto_compra:
        signal = "COMPRA"
    elif venta_conditions_met >= required and not veto_venta:
        signal = "VENTA"

    return signal, compra_items, venta_items, veto_compra, veto_venta
