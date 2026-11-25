"""
Demo Timestral (Mistral AI) - wrapper minimale per forecasting su dati pubblici.

Cosa fa:
  1. scarica un CSV pubblico (o legge un tuo file)
  2. backtest: nasconde gli ultimi H punti, li fa prevedere a Timestral (zero-shot)
     e li confronta con un baseline "seasonal naive" (stesso valore del ciclo precedente)
  3. previsione vera sui prossimi H punti, con intervallo di confidenza 10-90%
  4. salva grafico PNG + CSV con le previsioni

Uso:
  python timestral_demo.py                       # preset "energia" (ETTh1, orario)
  python timestral_demo.py --preset passeggeri   # serie mensile classica
  python timestral_demo.py --csv miei_dati.csv --date-col data --target vendite --season 7 --horizon 28
"""

import argparse
import time

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PRESETS = {
    # Carico/temperatura di un trasformatore elettrico, dati orari 2016-2018 (benchmark ETT)
    "energia": dict(
        csv="https://raw.githubusercontent.com/zhouhaoyi/ETDataset/main/ETT-small/ETTh1.csv",
        date_col="date", target="HUFL", covariates=["HULL", "MUFL", "MULL"],
        season=24, horizon=168, context=24 * 7 * 12,   # 1 settimana avanti, 12 settimane di storia
        title="Carico elettrico trasformatore (ETTh1, orario)",
    ),
    # Passeggeri aerei mensili 1949-1960: piccolo, stagionale, comprensibile da tutti
    "passeggeri": dict(
        csv="https://raw.githubusercontent.com/jbrownlee/Datasets/master/airline-passengers.csv",
        date_col="Month", target="Passengers", covariates=[],
        season=12, horizon=24, context=None,
        title="Passeggeri aerei mensili (1949-1960)",
    ),
}


def load_series(csv, date_col, target, covariates):
    df = pd.read_csv(csv, parse_dates=[date_col]).sort_values(date_col).reset_index(drop=True)
    cols = [target] + list(covariates or [])
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SystemExit(f"Colonne non trovate nel CSV: {missing}. Disponibili: {list(df.columns)}")
    return df[[date_col] + cols]


def seasonal_naive(history, horizon, season):
    """Baseline: ripete l'ultimo ciclo stagionale osservato."""
    last_cycle = history[-season:]
    reps = int(np.ceil(horizon / season))
    return np.tile(last_cycle, reps)[:horizon]


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def coverage(actual, lo, hi):
    actual = np.asarray(actual)
    return float(np.mean((actual >= lo) & (actual <= hi)))


def run_forecast(forecaster, values, horizon, past_cov=None):
    """values: (T,) target; past_cov: (C, T) covariate note solo nel passato, oppure None."""
    context = values[np.newaxis, np.newaxis, :]            # (series=1, variates=1, T)
    kwargs = {}
    if past_cov is not None and len(past_cov):
        kwargs["past_covariates"] = past_cov[np.newaxis, :, :]  # (1, C, T)
    t0 = time.perf_counter()
    fc = forecaster.forecast(context, prediction_length=horizon, **kwargs)
    elapsed = time.perf_counter() - t0
    return (
        np.asarray(fc.median)[0, 0],
        np.asarray(fc.quantile(0.1))[0, 0],
        np.asarray(fc.quantile(0.9))[0, 0],
        elapsed,
    )


def main():
    p = argparse.ArgumentParser(description="Demo forecasting con Timestral")
    p.add_argument("--preset", choices=PRESETS, default="energia")
    p.add_argument("--csv", help="URL o percorso di un CSV (sovrascrive il preset)")
    p.add_argument("--date-col")
    p.add_argument("--target")
    p.add_argument("--covariates", nargs="*", help="colonne extra usate come covariate passate")
    p.add_argument("--season", type=int, help="lunghezza ciclo stagionale (24=orario/giorno, 7=giornaliero/settimana, 12=mensile/anno)")
    p.add_argument("--horizon", type=int, help="quanti passi prevedere")
    p.add_argument("--context", type=int, help="quanti passi di storia usare (default: tutta)")
    p.add_argument("--model", default="mistralai/Timestral-28M",
                   help="5M (veloce) | 28M (default) | 123M | 209M (massima accuratezza)")
    p.add_argument("--device", default="cpu")
    p.add_argument("--out", default="timestral_demo")
    a = p.parse_args()

    cfg = dict(PRESETS[a.preset])
    if a.csv:
        cfg.update(csv=a.csv, covariates=[], context=None, title=a.target or "Serie")
    for k in ("date_col", "target", "season", "horizon", "context"):
        if getattr(a, k) is not None:
            cfg[k] = getattr(a, k)
    if a.covariates is not None:
        cfg["covariates"] = a.covariates
    for k in ("date_col", "target", "season", "horizon"):
        if cfg.get(k) is None:
            raise SystemExit(f"Con --csv specifica anche --{k.replace('_', '-')}")

    print(f"Carico dati: {cfg['csv']}")
    df = load_series(cfg["csv"], cfg["date_col"], cfg["target"], cfg["covariates"])
    if cfg.get("context"):
        df = df.iloc[-(cfg["context"] + cfg["horizon"]):].reset_index(drop=True)
    dates = df[cfg["date_col"]]
    y = df[cfg["target"]].to_numpy(dtype=float)
    cov = df[cfg["covariates"]].to_numpy(dtype=float).T if cfg["covariates"] else None
    H, S = cfg["horizon"], cfg["season"]
    print(f"{len(y)} punti, orizzonte {H}, stagionalità {S}, covariate: {cfg['covariates'] or 'nessuna'}")

    print(f"Carico modello {a.model} su {a.device} (primo avvio: download da Hugging Face)...")
    from timestral import TimestralForecaster
    forecaster = TimestralForecaster.from_pretrained(a.model, device=a.device)

    # --- 1) Backtest: nascondo gli ultimi H punti ---
    train, test = y[:-H], y[-H:]
    train_cov = cov[:, :-H] if cov is not None else None
    med, lo, hi, secs = run_forecast(forecaster, train, H, train_cov)
    naive = seasonal_naive(train, H, S)
    scale = mae(train[S:], train[:-S])  # errore medio del naive in-sample -> MASE
    res = {
        "MAE Timestral": mae(test, med),
        "MAE seasonal naive": mae(test, naive),
        "MASE Timestral": mae(test, med) / scale,
        "MASE seasonal naive": mae(test, naive) / scale,
        "Copertura intervallo 10-90%": coverage(test, lo, hi),
        "Tempo inferenza (s)": secs,
    }
    gain = 1 - res["MAE Timestral"] / res["MAE seasonal naive"]
    print("\n=== BACKTEST (ultimi", H, "punti nascosti) ===")
    for k, v in res.items():
        print(f"  {k:30s} {v:10.3f}")
    verdict = "riduce" if gain >= 0 else "aumenta"
    print(f"  -> Timestral {verdict} l'errore del {abs(gain):.0%} rispetto al baseline\n")

    # --- 2) Previsione vera sul futuro (le covariate servono solo sullo storico) ---
    f_med, f_lo, f_hi, _ = run_forecast(forecaster, y, H, cov)
    freq = pd.infer_freq(dates.iloc[-10:]) or (dates.iloc[-1] - dates.iloc[-2])
    future_dates = pd.date_range(dates.iloc[-1], periods=H + 1, freq=freq)[1:]
    out_csv = pd.DataFrame({"data": future_dates, "previsione": f_med, "p10": f_lo, "p90": f_hi})
    out_csv.to_csv(f"{a.out}_previsioni.csv", index=False)

    # --- 3) Grafico ---
    show = min(len(train), max(4 * H, 3 * S))
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    ax = axes[0]
    ax.plot(dates.iloc[-H - show:-H], train[-show:], color="#444", lw=1, label="storico")
    ax.plot(dates.iloc[-H:], test, color="#111", lw=1.6, label="reale (nascosto al modello)")
    ax.plot(dates.iloc[-H:], naive, color="#d98c1f", lw=1.2, ls="--", label=f"seasonal naive (MAE {res['MAE seasonal naive']:.2f})")
    ax.plot(dates.iloc[-H:], med, color="#2a6fdb", lw=1.6, label=f"Timestral (MAE {res['MAE Timestral']:.2f})")
    ax.fill_between(dates.iloc[-H:], lo, hi, color="#2a6fdb", alpha=0.18, label="intervallo 10-90%")
    ax.set_title(f"Backtest - {cfg['title']}  |  errore {-gain:+.0%} vs baseline")
    ax.legend(loc="upper left", fontsize=8)

    ax = axes[1]
    ax.plot(dates.iloc[-show:], y[-show:], color="#444", lw=1, label="storico")
    ax.plot(future_dates, f_med, color="#2a6fdb", lw=1.6, label="previsione Timestral")
    ax.fill_between(future_dates, f_lo, f_hi, color="#2a6fdb", alpha=0.18, label="intervallo 10-90%")
    ax.set_title(f"Previsione prossimi {H} passi")
    ax.legend(loc="upper left", fontsize=8)
    import matplotlib.dates as mdates
    for ax in axes:
        loc = mdates.AutoDateLocator(maxticks=8)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
        ax.grid(alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(f"{a.out}_grafico.png", dpi=130)
    print(f"Salvati: {a.out}_grafico.png, {a.out}_previsioni.csv")


if __name__ == "__main__":
    main()
