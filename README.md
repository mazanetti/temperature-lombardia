# Temperature Lombardia Forecast

Script Python per l'elaborazione automatica delle previsioni ensemble di temperatura delle sottozone climatiche della Lombardia tramite le API Open-Meteo, con lo scopo di fornire un Bollettino per posticipare/anticipare la stagione di accensione/spegnimento dell'impianto di riscaldamento in Lombardia.

Il processo:

1. Carica un dataset di comuni lombardi con coordinate geografiche e sottozone climatiche.
2. Seleziona un campione spazialmente rappresentativo di comuni per ciascuna sottozona.
3. Richiede le previsioni ensemble a Open-Meteo.
4. Calcola statistiche areali giornaliere.
5. Produce file Excel e grafici PNG.
6. Salva log dettagliati dell'esecuzione.

---

## Funzionalità

- Selezione spaziale dei comuni tramite algoritmo Maximin.
- Elaborazione delle sottozone climatiche lombarde.
- Utilizzo del modello ensemble ECMWF AIFS.
- Calcolo di:
  - temperatura media;
  - temperatura minima;
  - temperatura massima.
- Produzione automatica di:
  - file Excel;
  - grafici PNG;
  - log di esecuzione.
- Compatibile con Windows e Linux.
- Predisposto per esecuzioni automatiche e schedulate.

---

## Struttura del progetto

```text
project/
│
├── app
│   └── main.py
├── utility/
│   └── comuni_lombardia_zone_geo.csv
│
├── output/
│   ├── tabella_area01.xlsx
│   ├── tabella_area02.xlsx
│   └── ...
│
├── output/
│   └── immagini/
│       ├── grafico_1.png
│       ├── grafico_2.png
│       └── ...
│
└── log/
    └── temperature_lombardia_YYYY-MM-DD.log
```

---

## Dataset di input

Lo script richiede un file CSV contenente almeno le seguenti colonne:

```text
Comune
PROV
ISTAT
Sottozona
Latitudine
Longitudine
Altitudine
```

Percorso predefinito:

```text
utility/comuni_lombardia_zone_geo.csv
```

---

## Metodo di selezione dei comuni

Per ogni sottozona climatica:

1. Viene calcolato il centroide geografico dell'area.
2. Viene selezionato il comune più vicino al centroide.
3. Viene applicato un algoritmo **Maximin**.
4. Ogni nuovo comune viene scelto massimizzando la distanza minima rispetto ai comuni già selezionati.

L'obiettivo è ottenere un campione geograficamente distribuito ed evitare concentrazioni territoriali dovute all'ordine casuale del file CSV.

---

## Elaborazione delle previsioni

Per ogni sottozona:

- vengono selezionati fino a `MAX_COMUNI_PER_SOTTOZONA` comuni;
- viene effettuata una richiesta all'endpoint ensemble di Open-Meteo;
- vengono elaborate le variabili:
  - `temperature_2m_mean`
  - `temperature_2m_min`
  - `temperature_2m_max`
- vengono calcolate:
  - media areale;
  - deviazione standard areale.

La deviazione standard finale incorpora sia la dispersione dei membri ensemble sia la variabilità spaziale tra i comuni selezionati.

---

## Output generato

### File Excel

Per ogni sottozona viene generato un file:

```text
tabella_area01.xlsx
tabella_area02.xlsx
...
tabella_area08.xlsx
```

Contenente:

- data;
- temperatura media areale;
- temperatura minima areale;
- temperatura massima areale;
- deviazione standard associata.

---

### Grafici PNG

Per ogni sottozona viene prodotto un grafico:

```text
grafico_1.png
grafico_2.png
...
grafico_8.png
```

Ogni grafico mostra:

- temperatura minima media areale (Tmin);
- temperatura massima media areale (Tmax);
- barre di errore corrispondenti alla deviazione standard.

---

### Log di esecuzione

Ad ogni esecuzione viene creato un file:

```text
log/temperature_lombardia_YYYY-MM-DD.log
```

contenente:

- parametri utilizzati;
- elenco dei comuni selezionati;
- richieste API;
- eventuali errori;
- riepilogo finale dell'elaborazione.

---

## Configurazione

È possibile personalizzare il comportamento dell'applicazione tramite variabili d'ambiente.

Per partire dalla configurazione standard:

```bash
cp .env.example .env
```

e modificare i valori secondo le proprie esigenze.

### COMUNI_ZONE_PATH

Percorso del file CSV di input.

```bash
COMUNI_ZONE_PATH=/utility/comuni_lombardia_zone_geo.csv
```

### OUTPUT_FOLDER

Cartella dove salvare Excel e immagini.

```bash
OUTPUT_FOLDER=/output
```

### LOG_FOLDER

Cartella contenente i file di log.

```bash
LOG_FOLDER=log
```

### FORECAST_DAYS

Numero di giorni di previsione richiesti.

Default:

```bash
FORECAST_DAYS=15
```

### MODEL

Modello Open-Meteo da utilizzare.

Default:

```bash
MODEL=ecmwf_aifs025_ensemble
```

### MAX_COMUNI_PER_SOTTOZONA

Numero massimo di comuni selezionati per ogni sottozona.

Default:

```bash
MAX_COMUNI_PER_SOTTOZONA=10
```

### API_MAX_RETRIES

Numero massimo di tentativi in caso di errore temporaneo.

Default:

```bash
API_MAX_RETRIES=5
```

### PAUSA_TRA_RICHIESTE

Pausa tra due richieste API successive.

Default:

```bash
PAUSA_TRA_RICHIESTE=10
```

---

## Requisiti

- Python 3.11+
- Pandas
- NumPy
- Requests
- Matplotlib
- OpenPyXL
- urllib3

---

## Installazione

### Prerequisiti

- Python 3.12 o superiore
- uv

Installazione di uv:

```bash
pip install uv
```

---

### Creazione dell'ambiente virtuale

```bash
uv init --bare
uv python pin 3.12
# Crea l'ambiente virtuale con Python 3.12
uv venv --python 3.12
```

---

### Attivazione dell'ambiente virtuale

#### Windows

```bash
.venv\Scripts\activate
```

#### Linux

```bash
source .venv/bin/activate
```

---

### Installazione delle dipendenze

```bash
uv add pandas numpy requests matplotlib openpyxl urllib3
```

---

### Esecuzione

direttamente tramite uv:

```bash
uv run app/main.py
```
``
### Build Docker 
```bash
docker build -f docker/Dockerfile -t temperature-lombardia:local .
```

## Gestione errori

Lo script gestisce automaticamente:

- errori di connessione;
- timeout;
- errori HTTP 5xx;
- rate limiting HTTP 429;
- retry con backoff progressivo;
- risposte JSON non valide;
- coordinate geografiche mancanti o errate;
- file di input mancanti.

---

## Note tecniche

- Tutte le date sono gestite con timezone `Europe/Rome`.
- Matplotlib utilizza il backend `Agg`, permettendo l'esecuzione anche in ambienti privi di interfaccia grafica.
- Le immagini vengono generate direttamente su file senza necessità di display.
- Il progetto è stato pensato per esecuzioni pianificate e completamente automatiche.

---

## Licenza

ARPA Lombardia