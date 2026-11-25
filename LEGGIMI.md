# Demo Timestral – istruzioni

## Installazione (una volta, ~5 minuti)
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install git+https://github.com/mistralai/timestral.git pandas matplotlib
```
Serve Python ≥ 3.10. Niente GPU, niente account, niente chiave API: al primo avvio scarica i pesi da Hugging Face (111 MB per il modello 28M).

## Lancio
```bash
python timestral_demo.py                       # energia: carico elettrico orario, prevede 1 settimana
python timestral_demo.py --preset passeggeri   # passeggeri aerei mensili, prevede 2 anni
python timestral_demo.py --model mistralai/Timestral-209M   # modello più accurato (837 MB)
```

Con i tuoi dati (un CSV con una colonna data e una colonna numerica):
```bash
python timestral_demo.py --csv vendite.csv --date-col data --target vendite --season 7 --horizon 28
```
`--season`: 24 per dati orari, 7 per giornalieri, 12 per mensili.

## Cosa esce
- A video: errore di Timestral vs un baseline semplice ("stesso valore del ciclo scorso") sugli ultimi punti nascosti, più il tempo di calcolo.
- `timestral_demo_grafico.png`: sopra il backtest (reale vs previsto), sotto la previsione futura con fascia 10–90%.
- `timestral_demo_previsioni.csv`: previsioni con p10/p90, apribile in Excel.

## Da sapere prima di proporlo
I pesi hanno una licenza "Modified MIT": gratis, **ma non per aziende con fatturato consolidato oltre 20 M$ al mese** (~240 M$/anno). Sopra quella soglia serve una licenza commerciale da Mistral o i loro servizi gestiti. Va verificato prima di usarlo in produzione; per una prova interna su dati pubblici non c'è costo.

## Interfaccia web pubblicata (PC Linux)
- Indirizzo: http://localhost:8000/ (utente e password in `accesso_demo.json`).
  Si entra da una pagina di login (cookie di 30 giorni, valido solo sotto `/timestral`); `/timestral/logout` esce.
  Per script e curl funziona ancora l'autenticazione Basic (`curl -u demo:<password>`).
- Scheda **Order planner**: trasforma i quantili della previsione in quanto ordinare e confronta vendite perse e
  scorte avanzate (e il loro costo) con "previsione + scorta di sicurezza". Usa i backtest già salvati: è istantanea.
- **💬 Ask about this page** (pulsante in basso a destra, su ogni scheda): chat in inglese in un pannello laterale; a ogni domanda la pagina invia a Claude cosa si vede (scheda, dataset, serie, modello, testo e numeri visibili, dati dei grafici in forma compatta). Il server lancia la CLI di Claude (`claude -p`, login dell'abbonamento, niente
  API key) con i soli strumenti di forecast della demo (`webapp/mcp_forecaster.py`, server MCP senza dipendenze);
  nessuno strumento di sistema (shell, file). Variabili opzionali nel servizio: `TIMESTRAL_CHAT_MODEL` (default
  `opus`), `TIMESTRAL_CHAT_TIMEOUT` (secondi, default 240). Una domanda alla volta.
- **Agente della chat** (pulsante con il nome dell'agente nell'intestazione della chat → modal): Claude (CLI, predefinito),
  GPT (API OpenAI, serve la chiave), AI locale (server compatibile OpenAI sul PC, predefinito `http://127.0.0.1:8090/v1`,
  modello `inkling-2-mini-agent`; la demo non lo avvia: va avviato a parte, con llama.cpp serve `--jinja` per gli strumenti),
  oppure un'altra API compatibile OpenAI (OpenRouter, Mistral, …). "Test connection" prova il collegamento e carica i modelli.
  Impostazioni e chiavi in `agents_config.json` (permessi 600); le chiavi non tornano mai al browser.
- Gira come servizio utente systemd `timestral-demo` su 127.0.0.1:8000 (riparte da solo all'avvio del PC):
  `systemctl --user status|restart|stop timestral-demo` · log: `journalctl --user -u timestral-demo`.
- Esposto su internet con Tailscale Funnel sul percorso `/timestral`. Per toglierlo:
  `sudo tailscale funnel --https=443 --set-path=/timestral off` (non usare `--https=443 off`: spegnerebbe anche le altre app).
