#!/usr/bin/env python3
"""
Backtest de la estrategia de señales de compra/venta.
Recorre el historico dia a dia, usando SOLO los datos disponibles hasta
cada fecha (sin mirar al futuro), y compara cuantas veces se habria
disparado una señal con distintos umbrales de indicadores alineados.

Esto es un script de UN SOLO USO para validar la estrategia, no se
programa en el cron. Se ejecuta a mano y se lee el resultado en el log.
"""
from datetime import datetime, timezone

from report import get_market_chart, group_last
from signals import evaluate_signal

THRESHOLDS_TO_TEST = [4, 5]


def main():
    prices, volumes = get_market_chart(days=365)

    all_daily_closes = [p for _, p in prices]
    all_daily_volumes = [v for _, v in volumes]

    MIN_HISTORY = 210

    results_by_threshold = {t: [] for t in THRESHOLDS_TO_TEST}

    for i in range(MIN_HISTORY, len(all_daily_closes)):
        daily_closes_so_far = all_daily_closes[: i + 1]
        daily_volumes_so_far = all_daily_volumes[: i + 1]
        prices_so_far = prices[: i + 1]

        weekly_closes_so_far = group_last(
            prices_so_far, lambda dt: (dt.isocalendar()[0], dt.isocalendar()[1])
        )

        bullish_votes, bearish_votes = evaluate_signal(
            daily_closes_so_far, daily_volumes_so_far, weekly_closes_so_far
        )

        ts = prices[i][0]
        date_str = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        price_then = daily_closes_so_far[-1]
        price_after_7d = None
        if i + 7 < len(all_daily_closes):
            price_after_7d = all_daily_closes[i + 7]

        for threshold in THRESHOLDS_TO_TEST:
            signal = None
            count = 0
            if len(bullish_votes) >= threshold:
                signal = "COMPRA"
                count = len(bullish_votes)
            elif len(bearish_votes) >= threshold:
                signal = "VENTA"
                count = len(bearish_votes)

            if signal:
                results_by_threshold[threshold].append(
                    (date_str, signal, count, price_then, price_after_7d)
                )

    dias_evaluados = len(all_daily_closes) - MIN_HISTORY
    print(f"Dias evaluados: {dias_evaluados}")
    print("=" * 60)

    for threshold in THRESHOLDS_TO_TEST:
        results = results_by_threshold[threshold]
        print(f"\nUMBRAL: {threshold} indicadores")
        print(f"Total de señales disparadas: {len(results)}")
        print("-" * 60)

        for date_str, signal, count, price_then, price_after_7d in results:
            linea = f"{date_str} | {signal} ({count} indicadores) | precio: {price_then:,.0f} $"
            if price_after_7d is not None:
                variacion = ((price_after_7d - price_then) / price_then) * 100
                linea += f" | 7d despues: {price_after_7d:,.0f} $ ({variacion:+.1f}%)"
            print(linea)


if __name__ == "__main__":
    main()
