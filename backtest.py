#!/usr/bin/env python3
"""
Backtest de la ESTRATEGIA ESTRICTA (5 condiciones fijas de compra/venta).
Recorre el historico dia a dia usando solo datos disponibles hasta esa
fecha (sin mirar al futuro). Ejecucion de un solo uso, no se programa.

Muestra:
  - Los dias donde se cumplieron las 5 condiciones (señal completa)
  - Un resumen de cuantas condiciones (0 a 5) se cumplieron cada dia,
    para ver que tan cerca ha estado la estrategia de dispararse aunque
    no llegue a las 5, y decidir si conviene bajar el requisito.
"""
from collections import Counter
from datetime import datetime, timezone

from report import get_market_chart, group_last, get_fear_greed_history
from strategy import evaluate_strict_signal

REQUIRED = 5
MIN_HISTORY = 120


def main():
    prices, volumes = get_market_chart(days=365)
    fng_history = get_fear_greed_history(limit=400)

    all_daily_closes = [p for _, p in prices]

    compra_counts = Counter()
    venta_counts = Counter()
    signals_found = []
    dias_sin_fng = 0
    dias_evaluados = 0

    for i in range(MIN_HISTORY, len(all_daily_closes)):
        ts = prices[i][0]
        date_str = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        fng_value = fng_history.get(date_str)
        if fng_value is None:
            dias_sin_fng += 1
            continue

        daily_closes_so_far = all_daily_closes[: i + 1]
        prices_so_far = prices[: i + 1]
        weekly_closes_so_far = group_last(
            prices_so_far, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1])
        )

        signal, cond_compra, cond_venta = evaluate_strict_signal(
            daily_closes_so_far, weekly_closes_so_far, fng_value, required=REQUIRED
        )

        dias_evaluados += 1
        compra_counts[sum(cond_compra.values())] += 1
        venta_counts[sum(cond_venta.values())] += 1

        if signal:
            price_then = daily_closes_so_far[-1]
            price_after_7d = None
            if i + 7 < len(all_daily_closes):
                price_after_7d = all_daily_closes[i + 7]
            signals_found.append((date_str, signal, price_then, price_after_7d))

    print(f"Dias evaluados: {dias_evaluados} (sin dato F&G: {dias_sin_fng})")
    print(f"Requisito: {REQUIRED} de 5 condiciones")
    print("=" * 60)

    print(f"\nSEÑALES COMPLETAS DISPARADAS: {len(signals_found)}")
    print("-" * 60)
    for date_str, signal, price_then, price_after_7d in signals_found:
        linea = f"{date_str} | {signal} | precio: {price_then:,.0f} $"
        if price_after_7d is not None:
            variacion = ((price_after_7d - price_then) / price_then) * 100
            linea += f" | 7d despues: {price_after_7d:,.0f} $ ({variacion:+.1f}%)"
        print(linea)

    print("\n" + "=" * 60)
    print("DISTRIBUCION: cuantas condiciones de COMPRA se cumplieron cada dia")
    for n in range(5, -1, -1):
        print(f"  {n}/5 condiciones: {compra_counts.get(n, 0)} dias")

    print("\nDISTRIBUCION: cuantas condiciones de VENTA se cumplieron cada dia")
    for n in range(5, -1, -1):
        print(f"  {n}/5 condiciones: {venta_counts.get(n, 0)} dias")


if __name__ == "__main__":
    main()
