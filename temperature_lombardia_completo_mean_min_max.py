import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import requests
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import logging

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_DIR = Path(__file__).resolve().parent
TZ = ZoneInfo("Europe/Rome")
# =====================================================================
# CONFIGURAZIONE
# =====================================================================

#Cartella di log, se non c'è la creo e loggo tutto li
ESECUZIONE_GIORNO = (
    datetime.now(TZ)
    .strftime("%Y-%m-%d")
)

LOG_FOLDER = Path(
    os.getenv(
        "LOG_FOLDER",
        str(BASE_DIR / "log")
    )
)
LOG_FOLDER.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_FOLDER / f"temperature_lombardia_{ESECUZIONE_GIORNO}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ],
    force=True,
)
logger = logging.getLogger("temperature_lombardia")


class _LogWriter:
    """Scrive stdout/stderr anche nel file di log."""

    def __init__(self, level):
        self.level = level

    def write(self, message):
        if message and not message.isspace():
            logger.log(self.level, message.rstrip())

    def flush(self):
        pass


sys.stdout = _LogWriter(logging.INFO)
sys.stderr = _LogWriter(logging.ERROR)

# ---------------------------------------------------------------------
# File di input
# ---------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

# In Docker/Swarm i percorsi devono essere trasportabili: usa variabili
# d'ambiente se impostate, altrimenti usa la struttura del progetto locale.
COMUNI_ZONE_PATH = Path(
    os.getenv(
        "COMUNI_ZONE_PATH",
        str(
            BASE_DIR
            / "utility"
            / "comuni_lombardia_zone_geo.csv"
        )
    )
)



# ---------------------------------------------------------------------
# Cartelle di output
# ---------------------------------------------------------------------

OUTPUT_FOLDER = Path(
    os.getenv(
        "OUTPUT_FOLDER",
        str(BASE_DIR / "output")
    )
)


IMG_FOLDER = OUTPUT_FOLDER / "immagini"

# Crea le cartelle di output in modo sicuro anche in ambiente container
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
IMG_FOLDER.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------
# API Open-Meteo
# ---------------------------------------------------------------------

API_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

FORECAST_DAYS = int(
    os.getenv(
        "FORECAST_DAYS",
        "15"
    )
)
MODEL = os.getenv(
    "MODEL",
    "ecmwf_aifs025_ensemble"
)

# Numero massimo di comuni da selezionare per ciascuna sottozona.
MAX_COMUNI_PER_SOTTOZONA = int(
    os.getenv(
        "MAX_COMUNI_PER_SOTTOZONA",
        "10"
    )
)

logger.info("Esecuzione processo del %s", ESECUZIONE_GIORNO)

logger.info(
    "COMUNI_ZONE_PATH=%s",
    COMUNI_ZONE_PATH
)

logger.info(
    "OUTPUT_FOLDER=%s",
    OUTPUT_FOLDER
)

logger.info(
    "LOG_FOLDER=%s",
    LOG_FOLDER
)

logger.info(
    "FORECAST_DAYS=%s",
    FORECAST_DAYS
)

logger.info(
    "MAX_COMUNI_PER_SOTTOZONA=%s",
    MAX_COMUNI_PER_SOTTOZONA
)

# Timeout:
# - 10 secondi per la connessione
# - 90 secondi per la risposta
API_TIMEOUT = (10, 90)

# Numero massimo di tentativi in caso di errore temporaneo
API_MAX_RETRIES = int(
    os.getenv(
        "API_MAX_RETRIES",
        "5"
    )
)

# Pausa tra una richiesta API e la successiva.
# Utile per ridurre il rischio di HTTP 429.
PAUSA_TRA_RICHIESTE = int(
    os.getenv(
        "PAUSA_TRA_RICHIESTE",
        "10"
    )
)


# ---------------------------------------------------------------------
# Configurazione sottozone
# ---------------------------------------------------------------------

SOTTOZONE = range(1, 9)

# Numero massimo di comuni da selezionare per ciascuna sottozona.
#
# Esempio:
#   10 = massimo 10 comuni per sottozona
#   15 = massimo 15 comuni per sottozona
#
# Se una sottozona contiene meno comuni del valore indicato,
# vengono utilizzati tutti i comuni disponibili.
MAX_COMUNI_PER_SOTTOZONA = int(
    os.getenv(
        "MAX_COMUNI_PER_SOTTOZONA",
        "10"
    )
)


# ---------------------------------------------------------------------
# Variabili meteorologiche
# ---------------------------------------------------------------------

VARIABLES = [
    "temperature_2m_mean",
    "temperature_2m_min",
    "temperature_2m_max"
]


# =====================================================================
# FUNZIONI DI SUPPORTO
# =====================================================================


def crea_sessione():
    """
    Crea una sessione HTTP con retry automatici per errori temporanei.

    Il codice 429 viene gestito esplicitamente nella funzione
    richiedi_dati_api(), così da poter rispettare eventuali Retry-After.
    """

    session = requests.Session()

    retry_strategy = Retry(
        total=API_MAX_RETRIES,
        connect=API_MAX_RETRIES,
        read=API_MAX_RETRIES,
        status=API_MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
        respect_retry_after_header=True
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy
    )

    session.mount(
        "https://",
        adapter
    )

    session.mount(
        "http://",
        adapter
    )

    return session


# =====================================================================
# CARICAMENTO DATI COMUNI
# =====================================================================


def carica_dati_comuni():
    """
    Legge il file unico comuni_lombardia_zone_geo.csv.

    Il file deve contenere almeno:
        Comune
        Sottozona
        Latitudine
        Longitudine
        Altitudine
    """

    print("\n" + "=" * 70)
    print("CARICAMENTO DATI COMUNI")
    print("=" * 70)

    if not COMUNI_ZONE_PATH.exists():
        raise FileNotFoundError(
            f"File non trovato:\n{COMUNI_ZONE_PATH}"
        )

    # -------------------------------------------------------------
    # Lettura CSV
    # -------------------------------------------------------------

    df = pd.read_csv(
        COMUNI_ZONE_PATH,
        sep=",",
        encoding="utf-8-sig",
        engine="python",
        quotechar='"'
    )

    # -------------------------------------------------------------
    # Normalizzazione nomi colonne
    # -------------------------------------------------------------

    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
    )

    # -------------------------------------------------------------
    # Controllo colonne fondamentali
    # -------------------------------------------------------------

    colonne_richieste = {
        "Comune",
        "Sottozona",
        "Latitudine",
        "Longitudine",
        "Altitudine"
    }

    colonne_mancanti = (
        colonne_richieste
        - set(df.columns)
    )

    if colonne_mancanti:
        raise ValueError(
            "Mancano nel file "
            f"{COMUNI_ZONE_PATH.name} "
            "le colonne: "
            + ", ".join(sorted(colonne_mancanti))
        )

    # -------------------------------------------------------------
    # Normalizzazione Comune
    # -------------------------------------------------------------

    df["Comune"] = (
        df["Comune"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # -------------------------------------------------------------
    # Normalizzazione Sottozona
    # -------------------------------------------------------------

    df["Sottozona"] = (
        df["Sottozona"]
        .astype(str)
        .str.strip()
    )

    # -------------------------------------------------------------
    # Conversione coordinate
    # -------------------------------------------------------------

    for col in [
        "Latitudine",
        "Longitudine",
        "Altitudine"
    ]:

        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", ".", regex=False)
        )

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    # -------------------------------------------------------------
    # Controllo coordinate
    # -------------------------------------------------------------

    n_prima = len(df)

    df = df.dropna(
        subset=[
            "Latitudine",
            "Longitudine"
        ]
    ).copy()

    n_dopo = len(df)

    if n_dopo < n_prima:
        print(
            f"Attenzione: eliminate "
            f"{n_prima - n_dopo} righe "
            "con coordinate mancanti."
        )

    # -------------------------------------------------------------
    # Controllo valori plausibili
    # -------------------------------------------------------------

    df = df[
        df["Latitudine"].between(-90, 90)
        & df["Longitudine"].between(-180, 180)
    ].copy()

    if df.empty:
        raise ValueError(
            "Il file non contiene comuni con "
            "coordinate valide."
        )

    # -------------------------------------------------------------
    # Controllo generale
    # -------------------------------------------------------------

    print(
        f"Comuni caricati: {len(df)}"
    )

    print(
        f"Sottozone presenti: "
        f"{sorted(df['Sottozona'].dropna().unique())}"
    )

    print("\n--- CONTROLLO COORDINATE ---")

    print(
        df[
            [
                "Comune",
                "PROV",
                "Sottozona",
                "Latitudine",
                "Longitudine",
                "Altitudine"
            ]
        ]
        .head(20)
        .to_string(index=False)
    )

    print("----------------------------------")

    print(
        "\nIntervallo coordinate:"
    )

    print(
        f"  Latitudine : "
        f"{df['Latitudine'].min():.4f} "
        f"→ "
        f"{df['Latitudine'].max():.4f}"
    )

    print(
        f"  Longitudine: "
        f"{df['Longitudine'].min():.4f} "
        f"→ "
        f"{df['Longitudine'].max():.4f}"
    )

    print(
        f"  Altitudine : "
        f"{df['Altitudine'].min():.0f} "
        f"→ "
        f"{df['Altitudine'].max():.0f} m"
    )

    return df


# =====================================================================
# SELEZIONE SPAZIALE DEI COMUNI
# =====================================================================


def distanza_coordinate(
    lat1,
    lon1,
    lat2,
    lon2,
    lat_media
):
    """
    Calcola una distanza approssimata in km tra due coordinate.

    Per le dimensioni della Lombardia è sufficiente una
    proiezione locale semplice:

        1° latitudine  ≈ 111.32 km
        1° longitudine ≈ 111.32 * cos(latitudine) km
    """

    fattore_lat = 111.32

    fattore_lon = (
        111.32
        * np.cos(
            np.radians(lat_media)
        )
    )

    dx = (
        (lon2 - lon1)
        * fattore_lon
    )

    dy = (
        (lat2 - lat1)
        * fattore_lat
    )

    return np.sqrt(
        dx ** 2
        + dy ** 2
    )


def seleziona_comuni_spazialmente(
    df,
    numero_comuni
):
    """
    Seleziona un numero massimo di comuni distribuendoli
    regolarmente nello spazio mediante algoritmo maximin.

    Strategia:

    1. Il primo comune è quello più vicino al centroide
       geografico della sottozona.

    2. Ogni comune successivo è quello che massimizza
       la distanza minima rispetto ai comuni già selezionati.

    In questo modo i punti tendono a distribuirsi
    uniformemente sull'area invece di concentrarsi
    nell'ordine casuale del CSV.
    """

    if df.empty:
        return df.copy()

    # -------------------------------------------------------------
    # Elimina eventuali duplicati SOLO all'interno della sottozona.
    #
    # Lo stesso Comune può comunque comparire in sottozone diverse.
    # -------------------------------------------------------------

    df = (
        df
        .drop_duplicates(
            subset=[
                "ISTAT",
                "Latitudine",
                "Longitudine"
            ]
        )
        .copy()
    )

    # -------------------------------------------------------------
    # Se i comuni disponibili sono già <= al numero richiesto,
    # non serve effettuare la selezione spaziale.
    # -------------------------------------------------------------

    if len(df) <= numero_comuni:

        return (
            df
            .sort_values(
                ["Comune", "ISTAT"],
                kind="stable"
            )
            .reset_index(drop=True)
        )

    # -------------------------------------------------------------
    # Coordinate
    # -------------------------------------------------------------

    lat = df["Latitudine"].to_numpy(
        dtype=float
    )

    lon = df["Longitudine"].to_numpy(
        dtype=float
    )

    lat_media = float(
        np.mean(lat)
    )

    # -------------------------------------------------------------
    # Centroide geografico
    # -------------------------------------------------------------

    centroide_lat = float(
        np.mean(lat)
    )

    centroide_lon = float(
        np.mean(lon)
    )

    # -------------------------------------------------------------
    # Primo punto:
    # quello più vicino al centroide
    # -------------------------------------------------------------

    distanze_centroide = np.array([
        distanza_coordinate(
            centroide_lat,
            centroide_lon,
            lat[i],
            lon[i],
            lat_media
        )
        for i in range(len(df))
    ])

    primo_indice = int(
        np.argmin(
            distanze_centroide
        )
    )

    selezionati = [
        primo_indice
    ]

    candidati = set(
        range(len(df))
    )

    candidati.remove(
        primo_indice
    )

    # -------------------------------------------------------------
    # Algoritmo MAXIMIN
    # -------------------------------------------------------------

    while (
        len(selezionati)
        < numero_comuni
        and candidati
    ):

        migliore_indice = None
        migliore_distanza = -1.0

        for indice in candidati:

            distanza_minima = min(
                distanza_coordinate(
                    lat[indice],
                    lon[indice],
                    lat[sel],
                    lon[sel],
                    lat_media
                )
                for sel in selezionati
            )

            # -----------------------------------------------------
            # In caso di parità, ordine deterministico:
            # Comune + ISTAT.
            # -----------------------------------------------------

            if distanza_minima > migliore_distanza:

                migliore_distanza = (
                    distanza_minima
                )

                migliore_indice = (
                    indice
                )

            elif np.isclose(
                distanza_minima,
                migliore_distanza
            ):

                nome_attuale = (
                    str(
                        df.iloc[indice]["Comune"]
                    ),
                    str(
                        df.iloc[indice]["ISTAT"]
                    )
                )

                nome_migliore = (
                    str(
                        df.iloc[migliore_indice]["Comune"]
                    ),
                    str(
                        df.iloc[migliore_indice]["ISTAT"]
                    )
                )

                if nome_attuale < nome_migliore:
                    migliore_indice = indice

        selezionati.append(
            migliore_indice
        )

        candidati.remove(
            migliore_indice
        )

    # -------------------------------------------------------------
    # DataFrame finale
    # -------------------------------------------------------------

    df_selezionati = (
        df.iloc[selezionati]
        .copy()
        .reset_index(drop=True)
    )

    # -------------------------------------------------------------
    # Aggiunge l'ordine di selezione.
    # Utile per il controllo a video.
    # -------------------------------------------------------------

    df_selezionati.insert(
        0,
        "Ordine_Selezione",
        np.arange(
            1,
            len(df_selezionati) + 1
        )
    )

    return df_selezionati


# =====================================================================
# PREPARAZIONE SOTTOZONA
# =====================================================================


def prepara_sottozona(
    df_comuni_zone,
    sottozona
):
    """
    Estrae i comuni della sottozona e seleziona quelli da utilizzare
    nell'analisi mediante distribuzione spaziale regolare.
    """

    df = df_comuni_zone[
        df_comuni_zone["Sottozona"]
        .astype(str)
        .str.strip()
        == str(sottozona)
    ].copy()

    if df.empty:
        return None

    # -------------------------------------------------------------
    # Selezione spaziale
    # -------------------------------------------------------------

    n_disponibili = len(df)

    df = seleziona_comuni_spazialmente(
        df,
        MAX_COMUNI_PER_SOTTOZONA
    )

    # -------------------------------------------------------------
    # Controllo
    # -------------------------------------------------------------

    print(
        f"\n  Sottozona {sottozona}: "
        f"{n_disponibili} comuni disponibili"
    )

    print(
        f"  Comuni selezionati: "
        f"{len(df)}"
    )

    print("\n  --- SELEZIONE SPAZIALE ---")

    colonne_stampa = [
        "Comune",
        "Latitudine",
        "Longitudine",
        "Altitudine"
    ]

    if "Ordine_Selezione" in df.columns:

        colonne_stampa.insert(
            0,
            "Ordine_Selezione"
        )

    print(
        df[
            colonne_stampa
        ].to_string(index=False)
    )

    print(
        "  --------------------------"
    )

    return df


# =====================================================================
# RICHIESTA OPEN-METEO
# =====================================================================


def richiedi_dati_api(
    session,
    df_sottozona,
    sottozona
):
    """
    Effettua la chiamata Open-Meteo.

    Gestisce esplicitamente:
        - HTTP 429
        - HTTP 5xx
        - errori di connessione
        - errori SSL
        - JSON non valido

    con backoff progressivo.
    """

    lat_str = ",".join(
        f"{lat:.6f}"
        for lat in df_sottozona["Latitudine"]
    )

    lon_str = ",".join(
        f"{lon:.6f}"
        for lon in df_sottozona["Longitudine"]
    )

    params = {
        "latitude": lat_str,
        "longitude": lon_str,
        "daily": (
            "temperature_2m_mean,"
            "temperature_2m_min,"
            "temperature_2m_max"
        ),
        "forecast_days": FORECAST_DAYS,
        "models": MODEL
    }

    print(
        f"\n  → Richiesta API: "
        f"{len(df_sottozona)} comuni"
    )

    for tentativo in range(
        1,
        API_MAX_RETRIES + 1
    ):

        try:

            response = session.get(
                API_URL,
                params=params,
                timeout=API_TIMEOUT
            )

        except requests.RequestException as exc:

            print(
                f"  ERRORE di connessione "
                f"(tentativo {tentativo}/"
                f"{API_MAX_RETRIES}):"
            )

            print(
                f"  {type(exc).__name__}: {exc}"
            )

            if tentativo >= API_MAX_RETRIES:

                print(
                    f"  Sottozona {sottozona}: "
                    f"richiesta fallita definitivamente."
                )

                return None

            attesa = min(
                60,
                5 * (2 ** (tentativo - 1))
            )

            print(
                f"  Nuovo tentativo tra "
                f"{attesa} secondi..."
            )

            time.sleep(attesa)

            continue

        # ---------------------------------------------------------
        # HTTP 200
        # ---------------------------------------------------------

        if response.status_code == 200:

            try:

                data = response.json()

            except ValueError:

                print(
                    f"  ERRORE API sottozona "
                    f"{sottozona}: "
                    f"risposta JSON non valida."
                )

                if tentativo >= API_MAX_RETRIES:
                    return None

                attesa = min(
                    60,
                    5 * (2 ** (tentativo - 1))
                )

                print(
                    f"  Nuovo tentativo tra "
                    f"{attesa} secondi..."
                )

                time.sleep(attesa)

                continue

            if not isinstance(data, list):

                print(
                    f"  ERRORE API sottozona "
                    f"{sottozona}: "
                    f"formato risposta inatteso."
                )

                return None

            if not data:

                print(
                    f"  ERRORE API sottozona "
                    f"{sottozona}: "
                    f"risposta vuota."
                )

                return None

            return data

        # ---------------------------------------------------------
        # HTTP 429 - Too Many Requests
        # ---------------------------------------------------------

        if response.status_code == 429:

            retry_after = response.headers.get(
                "Retry-After"
            )

            try:
                attesa = int(
                    retry_after
                )
            except (
                TypeError,
                ValueError
            ):
                attesa = min(
                    120,
                    10 * (2 ** (tentativo - 1))
                )

            print(
                f"  HTTP 429 - troppe richieste "
                f"(tentativo {tentativo}/"
                f"{API_MAX_RETRIES})."
            )

            if tentativo >= API_MAX_RETRIES:

                print(
                    f"  Sottozona {sottozona}: "
                    f"limite API raggiunto."
                )

                return None

            print(
                f"  Attesa prima del nuovo tentativo: "
                f"{attesa} secondi."
            )

            time.sleep(attesa)

            continue

        # ---------------------------------------------------------
        # HTTP 5xx
        # ---------------------------------------------------------

        if response.status_code >= 500:

            print(
                f"  HTTP {response.status_code} "
                f"(tentativo {tentativo}/"
                f"{API_MAX_RETRIES})."
            )

            if tentativo >= API_MAX_RETRIES:

                print(
                    f"  Sottozona {sottozona}: "
                    f"errore server persistente."
                )

                return None

            attesa = min(
                60,
                5 * (2 ** (tentativo - 1))
            )

            print(
                f"  Nuovo tentativo tra "
                f"{attesa} secondi..."
            )

            time.sleep(attesa)

            continue

        # ---------------------------------------------------------
        # Altri errori HTTP
        # ---------------------------------------------------------

        print(
            f"  ERRORE API sottozona "
            f"{sottozona}: "
            f"HTTP {response.status_code}"
        )

        try:

            testo = response.text[:500]

            if testo:
                print(
                    f"  Risposta server: "
                    f"{testo}"
                )

        except Exception:
            pass

        return None

    return None


# =====================================================================
# COSTRUZIONE DATAFRAME API
# =====================================================================


def costruisci_dataframe_api(
    data,
    sottozona
):
    """
    Trasforma la risposta Open-Meteo in un unico DataFrame.
    """

    dfs = []

    for i, item in enumerate(data):

        if not isinstance(
            item,
            dict
        ):

            print(
                f"  Attenzione: elemento {i} "
                f"della risposta non valido."
            )

            continue

        daily = item.get(
            "daily"
        )

        if not isinstance(
            daily,
            dict
        ):

            print(
                f"  Attenzione: dati daily "
                f"mancanti per elemento {i}."
            )

            continue

        if "time" not in daily:

            print(
                f"  Attenzione: asse temporale "
                f"mancante per elemento {i}."
            )

            continue

        df = pd.DataFrame(
            daily
        )

        if not df.empty:
            dfs.append(
                df
            )

    if not dfs:

        print(
            f"  Nessun dato utilizzabile "
            f"per sottozona {sottozona}."
        )

        return None

    all_data = pd.concat(
        dfs,
        ignore_index=True
    )

    # -------------------------------------------------------------
    # Conversione data
    # -------------------------------------------------------------

    all_data["time"] = pd.to_datetime(
        all_data["time"],
        errors="coerce"
    )

    all_data = all_data.dropna(
        subset=["time"]
    )

    if all_data.empty:
        return None

    all_data = (
        all_data
        .sort_values("time")
        .reset_index(drop=True)
    )

    return all_data


# =====================================================================
# STATISTICHE COMUNE
# =====================================================================


def calcola_statistiche_comune(
    df,
    varname
):
    """
    Calcola media e deviazione standard dei membri ensemble
    per ciascun comune e giorno.
    """

    member_cols = [
        col
        for col in df.columns
        if col.startswith(
            f"{varname}_member"
        )
    ]

    if not member_cols:

        df[
            f"{varname}_commune_mean"
        ] = np.nan

        df[
            f"{varname}_commune_std"
        ] = np.nan

        return df

    df[
        f"{varname}_commune_mean"
    ] = (
        df[member_cols]
        .mean(axis=1)
    )

    df[
        f"{varname}_commune_std"
    ] = (
        df[member_cols]
        .std(axis=1)
    )

    return df


# =====================================================================
# STATISTICHE AREALI
# =====================================================================


def calcola_statistiche_areali(
    all_data
):
    """
    Calcola media e deviazione standard areale giornaliera.

    La deviazione standard areale combina:

    - dispersione ensemble del singolo comune;
    - variabilità spaziale tra i comuni.

    Formula:

        sqrt(
            mean(
                std_i^2
                +
                (mean_i - mean_areale)^2
            )
        )

    dove:
        mean_i = media ensemble del comune i
        std_i  = deviazione standard ensemble del comune i
    """

    daily_stats = []

    for date, group in all_data.groupby(
        "time"
    ):

        row = {
            "date": date
        }

        for var in VARIABLES:

            mean_col = (
                f"{var}_commune_mean"
            )

            std_col = (
                f"{var}_commune_std"
            )

            # -----------------------------------------------------
            # Mantiene accoppiate media e deviazione standard
            # dello stesso comune.
            # -----------------------------------------------------

            stats = group[
                [
                    mean_col,
                    std_col
                ]
            ].copy()

            stats[mean_col] = pd.to_numeric(
                stats[mean_col],
                errors="coerce"
            )

            stats[std_col] = pd.to_numeric(
                stats[std_col],
                errors="coerce"
            )

            stats = stats.dropna(
                subset=[
                    mean_col,
                    std_col
                ]
            )

            if stats.empty:

                row[
                    f"{var}_areale_mean"
                ] = np.nan

                row[
                    f"{var}_areale_std"
                ] = np.nan

                continue

            mean_row = (
                stats[mean_col]
                .to_numpy(
                    dtype=float
                )
            )

            std_row = (
                stats[std_col]
                .to_numpy(
                    dtype=float
                )
            )

            # -----------------------------------------------------
            # Media areale
            # -----------------------------------------------------

            mean_areale = np.mean(
                mean_row
            )

            # -----------------------------------------------------
            # Deviazione standard areale
            # -----------------------------------------------------

            std_areale = np.sqrt(
                np.mean(
                    std_row ** 2
                    +
                    (
                        mean_row
                        - mean_areale
                    ) ** 2
                )
            )

            row[
                f"{var}_areale_mean"
            ] = round(
                mean_areale,
                2
            )

            row[
                f"{var}_areale_std"
            ] = round(
                std_areale,
                2
            )

        daily_stats.append(
            row
        )

    if not daily_stats:
        return pd.DataFrame()

    daily_stats = pd.DataFrame(
        daily_stats
    )

    daily_stats = (
        daily_stats
        .sort_values("date")
        .reset_index(drop=True)
    )

    return daily_stats


# =====================================================================
# SALVATAGGIO EXCEL
# =====================================================================


def salva_excel(
    daily_stats,
    sottozona
):
    """
    Salva il risultato della sottozona nel file Excel previsto.
    """

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    out_path = (
        OUTPUT_FOLDER
        / f"tabella_area0{sottozona}.xlsx"
    )

    daily_stats.to_excel(
        out_path,
        index=False
    )

    return out_path


# =====================================================================
# FASE 1 - ACQUISIZIONE E CALCOLO
# =====================================================================


def esegui_acquisizione():

    df_comuni_zone = (
        carica_dati_comuni()
    )

    session = crea_sessione()

    print("\n" + "=" * 70)
    print("ACQUISIZIONE DATI OPEN-METEO")
    print("=" * 70)

    risultati = {}

    sottozone_fallite = []

    for indice_sottozona, sottozona in enumerate(
        SOTTOZONE
    ):

        print(
            f"\n--- Sottozona {sottozona} ---"
        )

        # ---------------------------------------------------------
        # Preparazione sottozona
        # ---------------------------------------------------------

        df_sottozona = (
            prepara_sottozona(
                df_comuni_zone,
                sottozona
            )
        )

        if df_sottozona is None:

            print(
                f"  Nessun comune con "
                f"coordinate valide "
                f"per sottozona {sottozona}. "
                f"Skip."
            )

            sottozone_fallite.append(
                sottozona
            )

            continue

        print(
            f"\n  Comuni utilizzati: "
            f"{len(df_sottozona)}"
        )

        # ---------------------------------------------------------
        # Pausa tra richieste
        # ---------------------------------------------------------

        if indice_sottozona > 0:

            print(
                f"\n  Pausa di "
                f"{PAUSA_TRA_RICHIESTE} "
                f"secondi prima della richiesta..."
            )

            time.sleep(
                PAUSA_TRA_RICHIESTE
            )

        # ---------------------------------------------------------
        # Chiamata API
        # ---------------------------------------------------------

        data = richiedi_dati_api(
            session,
            df_sottozona,
            sottozona
        )
        
        if data is None:

            sottozone_fallite.append(
                sottozona
            )

            continue

        # ---------------------------------------------------------
        # DataFrame
        # ---------------------------------------------------------

        all_data = (
            costruisci_dataframe_api(
                data,
                sottozona
            )
        )

        if all_data is None:

            sottozone_fallite.append(
                sottozona
            )

            continue

        # ---------------------------------------------------------
        # Rimuove giorno corrente
        # ---------------------------------------------------------

        today = (
            pd.Timestamp.now(
                tz="Europe/Rome"
            )
            .normalize()
            .tz_localize(None)
        )

        all_data = all_data[
            all_data["time"] > today
        ].copy()

        if all_data.empty:

            print(
                f"  Nessun giorno futuro "
                f"disponibile per "
                f"sottozona {sottozona}."
            )

            sottozone_fallite.append(
                sottozona
            )

            continue

        # ---------------------------------------------------------
        # Calcolo statistiche membri ensemble
        # ---------------------------------------------------------

        for var in VARIABLES:

            all_data = (
                calcola_statistiche_comune(
                    all_data,
                    var
                )
            )

        # ---------------------------------------------------------
        # Calcolo statistiche areali
        # ---------------------------------------------------------

        daily_stats = (
            calcola_statistiche_areali(
                all_data
            )
        )

        if daily_stats.empty:

            print(
                f"  Nessuna statistica "
                f"disponibile per "
                f"sottozona {sottozona}."
            )

            sottozone_fallite.append(
                sottozona
            )

            continue

        # ---------------------------------------------------------
        # Salvataggio Excel
        # ---------------------------------------------------------


        out_path = salva_excel(
            daily_stats,
            sottozona
        )

        risultati[
            sottozona
        ] = daily_stats

        print(
            f"\n  OK → {out_path.name} "
            f"({len(daily_stats)} giorni)"
        )

    session.close()

    # -------------------------------------------------------------
    # Riepilogo acquisizione
    # -------------------------------------------------------------

    print("\n" + "=" * 70)
    print("RIEPILOGO ACQUISIZIONE")
    print("=" * 70)

    print(
        f"Sottozone elaborate correttamente: "
        f"{len(risultati)}"
    )

    if risultati:

        print(
            "Sottozone OK: "
            + ", ".join(
                str(x)
                for x in sorted(
                    risultati.keys()
                )
            )
        )

    if sottozone_fallite:

        print(
            "Sottozone non elaborate: "
            + ", ".join(
                str(x)
                for x in sorted(
                    sottozone_fallite
                )
            )
        )

    else:

        print(
            "Nessuna sottozona fallita."
        )

    return risultati


# =====================================================================
# FASE 2 - LETTURA DEGLI EXCEL
# =====================================================================


def carica_excel_sottozone():
    """
    Legge esclusivamente gli Excel delle sottozone prodotti
    dallo script.
    """

    dfs = {}

    print("\n" + "=" * 70)
    print("CARICAMENTO FILE EXCEL")
    print("=" * 70)

    for sottozona in SOTTOZONE:

        filename = (
            f"tabella_area0{sottozona}.xlsx"
        )

        file_path = (
            OUTPUT_FOLDER
            / filename
        )

        if not file_path.exists():

            print(
                f"  Sottozona {sottozona}: "
                f"file non presente, skip."
            )

            continue

        try:

            df = pd.read_excel(
                file_path
            )

        except Exception as exc:

            print(
                f"  ERRORE lettura "
                f"{filename}: {exc}"
            )

            continue

        # ---------------------------------------------------------
        # Controllo colonne necessarie
        # ---------------------------------------------------------

        colonne_richieste = [
            "date",
            "temperature_2m_min_areale_mean",
            "temperature_2m_min_areale_std",
            "temperature_2m_max_areale_mean",
            "temperature_2m_max_areale_std"
        ]

        colonne_mancanti = [
            col
            for col in colonne_richieste
            if col not in df.columns
        ]

        if colonne_mancanti:

            print(
                f"  ERRORE {filename}: "
                f"colonne mancanti: "
                f"{', '.join(colonne_mancanti)}"
            )

            continue

        # ---------------------------------------------------------
        # Conversione date
        # ---------------------------------------------------------

        df["date"] = pd.to_datetime(
            df["date"],
            errors="coerce"
        )

        df = (
            df
            .dropna(subset=["date"])
            .sort_values("date")
        )

        dfs[
            sottozona
        ] = df

        print(
            f"  OK → {filename}"
        )

    return dfs


# =====================================================================
# FASE 3 - GRAFICA
# =====================================================================


def crea_grafici(
    dfs
):
    """
    Crea i grafici Tmin/Tmax per tutte le sottozone.
    """

    IMG_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    print("\n" + "=" * 70)
    print("GENERAZIONE GRAFICI")
    print("=" * 70)

    # -----------------------------------------------------------------
    # Abbreviazioni italiane dei giorni.
    # Evita dipendenza dalla configurazione locale di Windows.
    # -----------------------------------------------------------------

    giorni_italiani = [
        "Lun",
        "Mar",
        "Mer",
        "Gio",
        "Ven",
        "Sab",
        "Dom"
    ]

    # -----------------------------------------------------------------
    # Ciclo ordinato sulle sottozone
    # -----------------------------------------------------------------

    for sottozona in sorted(
        dfs
    ):

        df = (
            dfs[sottozona]
            .copy()
        )

        fig, ax = plt.subplots(
            figsize=(15, 6)
        )

        # -------------------------------------------------------------
        # Tmin
        # -------------------------------------------------------------

        ax.errorbar(
            df["date"],
            df[
                "temperature_2m_min_areale_mean"
            ],
            yerr=df[
                "temperature_2m_min_areale_std"
            ],
            fmt="o",
            color="blue",
            ecolor="lightblue",
            elinewidth=2,
            capsize=4,
            label="Tmin",
            markersize=13
        )

        # -------------------------------------------------------------
        # Tmax
        # -------------------------------------------------------------

        ax.errorbar(
            df["date"],
            df[
                "temperature_2m_max_areale_mean"
            ],
            yerr=df[
                "temperature_2m_max_areale_std"
            ],
            fmt="o",
            color="red",
            ecolor="salmon",
            elinewidth=2,
            capsize=4,
            label="Tmax",
            markersize=13
        )

        # -------------------------------------------------------------
        # Griglia
        # -------------------------------------------------------------

        ax.grid(
            axis="y",
            which="major",
            linestyle="--",
            color="gray",
            alpha=0.2
        )

        # -------------------------------------------------------------
        # Asse X
        # -------------------------------------------------------------

        ax.xaxis.set_major_locator(
            mdates.DayLocator(
                interval=1
            )
        )

        ax.xaxis.set_major_formatter(
            mdates.DateFormatter(
                "%d/%m"
            )
        )

        # -------------------------------------------------------------
        # Etichette X in italiano
        # -------------------------------------------------------------

        tick_labels = []

        for date in df["date"]:

            giorno = (
                giorni_italiani[
                    date.weekday()
                ]
            )

            tick_labels.append(
                f"{giorno} "
                f"{date.strftime('%d/%m')}"
            )

        ax.set_xticks(
            df["date"]
        )

        ax.set_xticklabels(
            tick_labels,
            rotation=45,
            fontsize=14
        )

        # -------------------------------------------------------------
        # Asse Y
        # -------------------------------------------------------------

        ax.yaxis.set_major_locator(
            plt.MultipleLocator(2)
        )

        ax.tick_params(
            axis="y",
            labelsize=14
        )

        # -------------------------------------------------------------
        # Spines
        # -------------------------------------------------------------

        ax.spines[
            "top"
        ].set_visible(False)

        ax.spines[
            "right"
        ].set_visible(False)

        # -------------------------------------------------------------
        # Titoli
        # -------------------------------------------------------------

        ax.set_title(
            f"Sottozona {sottozona}",
            fontsize=16
        )

        ax.set_xlabel(
            ""
        )

        ax.set_ylabel(
            "Temperatura [°C]",
            fontsize=16
        )

        ax.legend()

        # -------------------------------------------------------------
        # Layout
        # -------------------------------------------------------------

        fig.tight_layout()

        # -------------------------------------------------------------
        # Salvataggio
        # -------------------------------------------------------------

        out_file = (
            IMG_FOLDER
            / f"grafico_{sottozona}.png"
        )

        fig.savefig(
            out_file,
            dpi=300,
            bbox_inches="tight"
        )

        # -------------------------------------------------------------
        # Chiusura figura
        # -------------------------------------------------------------

        plt.close(
            fig
        )

        print(
            f"  OK → {out_file}"
        )


# =====================================================================
# MAIN
# =====================================================================


def main():

    start_time = time.time()

    print("\n")
    print("=" * 70)
    print(
        "ELABORAZIONE TEMPERATURE "
        "SOTTOZONE LOMBARDIA"
    )
    print("=" * 70)

    print(
        f"\nFile input:"
    )

    print(
        f"  {COMUNI_ZONE_PATH}"
    )

    print(
        f"\nNumero massimo comuni per sottozona:"
    )

    print(
        f"  {MAX_COMUNI_PER_SOTTOZONA}"
    )

    print(
        f"\nPausa tra richieste API:"
    )

    print(
        f"  {PAUSA_TRA_RICHIESTE} secondi"
    )

    try:

        # -------------------------------------------------------------
        # FASE 1
        # -------------------------------------------------------------

        esegui_acquisizione()

        # -------------------------------------------------------------
        # FASE 2
        # -------------------------------------------------------------

        dfs = (
            carica_excel_sottozone()
        )

        if not dfs:

            raise RuntimeError(
                "Nessun file Excel valido "
                "disponibile per la "
                "generazione dei grafici."
            )

        # -------------------------------------------------------------
        # FASE 3
        # -------------------------------------------------------------

        crea_grafici(
            dfs
        )

    except Exception as exc:

        print(
            "\n" + "=" * 70
        )

        print(
            "ERRORE FATALE"
        )

        print(
            "=" * 70
        )

        print(
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        raise

    finally:

        elapsed = (
            time.time()
            - start_time
        )

        print(
            "\n" + "=" * 70
        )

        print(
            f"ELABORAZIONE TERMINATA "
            f"in {elapsed:.1f} secondi"
        )

        print(
            "=" * 70
        )


# =====================================================================
# AVVIO
# =====================================================================


if __name__ == "__main__":
    main()