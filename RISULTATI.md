# Risultati demo Timestral (Mistral AI)

*Esecuzione del 2 novembre 2026 su un normale PC da ufficio, solo CPU. Tutti i numeri qui sotto vengono da esecuzioni reali di `timestral_demo.py`.*

## Cosa abbiamo misurato

Per ogni serie abbiamo **nascosto al modello l'ultimo tratto di dati** (una settimana per l'energia, due anni per i passeggeri) e gli abbiamo chiesto di prevederlo. Poi abbiamo confrontato la previsione con i valori veri e con un metodo semplice di riferimento ("baseline": ripetere identico l'ultimo ciclo, cioè l'ultimo giorno o l'ultimo anno).

- **MAE** = errore medio della previsione, nelle unità del dato (più basso è meglio).
- **Copertura 10-90%** = quante volte il valore vero è caduto dentro la fascia di incertezza indicata dal modello. Il valore ideale è circa **80%**.

| Dataset | Modello | MAE Timestral | MAE baseline | Miglioramento | Copertura 10-90% | Tempo di inferenza |
|---|---|---:|---:|---:|---:|---:|
| Energia (carico orario trasformatore, prev. 1 settimana) | Timestral-28M | 2,743 | 4,195 | **-35% errore** | 88,7% | 0,55 s |
| Passeggeri aerei (mensili, prev. 2 anni) | Timestral-28M | 39,91 | 71,25 | **-44% errore** | 45,8% | 0,05 s |
| Energia (carico orario trasformatore, prev. 1 settimana) | Timestral-209M | 2,705 | 4,195 | **-36% errore** | 85,1% | 4,55 s |

## Cosa dimostrano

1. **Funziona "così com'è"**: senza nessun addestramento sui nostri dati, Timestral ha ridotto l'errore del 35-44% rispetto al metodo semplice, su due serie molto diverse (dati orari con covariate e dati mensili con trend).
2. **È veloce su un PC normale**: una previsione richiede da meno di un decimo di secondo a circa 4,5 secondi, senza scheda grafica.
3. **Il modello grande non vale (qui) il costo**: il 209M migliora appena l'1% rispetto al 28M, ma è circa 8 volte più lento e pesa 837 MB invece di 111 MB. Per partire basta il 28M.
4. **Punto debole: l'incertezza sui passeggeri**. La fascia 10-90% ha contenuto il valore vero solo nel 46% dei casi (dovrebbe essere ~80%): il modello ha sottostimato la crescita del traffico e si è mostrato "troppo sicuro di sé". Sull'energia invece la fascia è affidabile (85-89%). Inoltre ogni test è su un solo periodo: sono indicazioni promettenti, non una garanzia.

## Macchina usata

| | |
|---|---|
| CPU | Intel Core i5-6600K @ 3,50 GHz (4 core / 4 thread, del 2015) |
| RAM | 16 GB |
| Sistema operativo | Windows 10 Pro (build 19045) |
| GPU | presente (RTX 3080 Ti) ma **non usata**: PyTorch installato in versione solo CPU |
| Software | Python 3.14.3, torch 2.15.0 (CPU), timestral 1.0.0, pandas 3.1.0 |

## Costi e licenza

- **Modello gratuito**: pesi scaricabili da Hugging Face, nessun account o chiave API necessari.
- **Nessuna GPU necessaria**: gira su un PC da ufficio anche datato.
- **Attenzione alla licenza**: i pesi sono rilasciati con licenza "Modified MIT", che **non copre le aziende con fatturato consolidato superiore a 20 M$ al mese** (~240 M$/anno). Sopra quella soglia serve una **licenza commerciale Mistral** (o i loro servizi gestiti). Va verificato con l'ufficio legale prima di qualsiasi uso in produzione.
- **Prezzi API / Forge di Mistral: non pubblicati** al momento; vanno richiesti a Mistral.

## Prossimo passo suggerito

Provarlo su un export di dati aziendali (es. vendite giornaliere), restando in locale:

```
.venv\Scripts\python.exe timestral_demo.py --csv vendite.csv --date-col data --target vendite --season 7 --horizon 28 --out output/vendite
```

`--season`: 24 per dati orari, 7 per giornalieri, 12 per mensili. I dati non escono dal PC.

## File prodotti

- `output/energia_grafico.png`, `output/energia_previsioni.csv`
- `output/passeggeri_grafico.png`, `output/passeggeri_previsioni.csv`
- `output/energia_209M_grafico.png`, `output/energia_209M_previsioni.csv`

Nei grafici: in alto il test (reale in nero, Timestral in blu, baseline arancione tratteggiato), in basso la previsione futura con la fascia di incertezza.

## Note tecniche

- `timestral_demo.py` **non è stato modificato**: tutti e tre gli step sono riusciti al primo colpo una volta disponibili i pesi.
- La connessione a huggingface.co da questa rete è **instabile** (connessioni chiuse a metà, circa 2 tentativi su 3). Ho scaricato i pesi in anticipo ripetendo i tentativi, poi ho eseguito la demo con `HF_HUB_OFFLINE=1` (usa la cache locale). Se il primo avvio fallisce con `WinError 10054`, basta rilanciare.
- I pesi sono in cache in `A:\hf-cache\hub` (28M e 209M).
