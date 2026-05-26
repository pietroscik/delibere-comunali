import streamlit as st
import pandas as pd
import os
import json
from pathlib import Path

# Percorsi dati robusti rispetto alla cartella corrente di esecuzione.
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR / "albo_download"
TEXTS_DIR = BASE_DIR / "texts"

# --- Funzioni di Supporto ---
@st.cache_data
def load_data(file_name):
    """Carica un file CSV dalla directory base."""
    path = BASE_DIR / file_name
    if path.exists():
        try:
            return pd.read_csv(path)
        except Exception as e:
            st.error(f"Errore durante il caricamento di {file_name}: {e}")
            return None
    return None

@st.cache_data
def load_jsonl(file_name):
    """Carica un file JSONL dalla directory base."""
    path = BASE_DIR / file_name
    if path.exists():
        data = []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    data.append(json.loads(line))
            return pd.DataFrame(data)
        except Exception as e:
            st.error(f"Errore durante il caricamento di {file_name}: {e}")
            return None
    return None

def get_raw_text(file_id):
    """Recupera il contenuto testuale grezzo per un dato file_id."""
    # Si assume che file_id corrisponda al nome base del file .txt
    text_path = TEXTS_DIR / f"{file_id}.txt"
    if text_path.exists():
        try:
            with open(text_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Errore durante la lettura del testo: {e}"
    return "Testo non trovato o file non esistente."

# --- Layout dell'App Streamlit ---
st.set_page_config(layout="wide", page_title="Strategia di Comprensione PDF Online")

st.title("Strategia di Comprensione PDF per Delibere Comunali")
st.markdown("""
Questa applicazione web dimostra come i dati scaricati e i risultati dell'analisi dei PDF
possono essere caricati e visualizzati online per comprendere e validare la strategia di estrazione.
""")

# --- Carica Dati ---
df_metadati = load_data("albo_metadati.csv")
df_parsed = load_data("allegati_parsed.csv")
df_features = load_data("documenti_features.csv")
df_corpus = load_jsonl("documenti_corpus.jsonl")

# --- Navigazione Sidebar ---
st.sidebar.header("Navigazione")
page = st.sidebar.radio("Seleziona una sezione:",
                        ["Panoramica Dati", "Dettaglio Documento", "Strategia di Comprensione", "Integrazione Modelli"])

# --- Contenuto delle Pagine ---
if page == "Panoramica Dati":
    st.header("Panoramica dei Dati Scaricati e Analizzati")

    if df_metadati is not None:
        st.subheader("Metadati di Scraping (`albo_metadati.csv`)")
        st.dataframe(df_metadati.head())
        st.write(f"Totale documenti scaricati: {len(df_metadati)}")
    else:
        st.warning("File `albo_metadati.csv` non trovato. Esegui `albo_scraper.py`.")

    if df_parsed is not None:
        st.subheader("Dati Estratti dai Documenti (`allegati_parsed.csv`)")
        st.dataframe(df_parsed.head())
        st.write(f"Totale documenti analizzati: {len(df_parsed)}")
    else:
        st.info("File `allegati_parsed.csv` non trovato. Esegui `analyze_albo.py`.")

    if df_features is not None:
        st.subheader("Feature Analitiche (`documenti_features.csv`)")
        st.dataframe(df_features.head())
        st.write(f"Totale feature estratte: {len(df_features)}")
    else:
        st.info("File `documenti_features.csv` non trovato. Esegui `analyze_albo.py`.")

    if df_corpus is not None:
        st.subheader("Corpus per RAG/ML (`documenti_corpus.jsonl`)")
        st.dataframe(df_corpus.head())
        st.write(f"Totale documenti nel corpus: {len(df_corpus)}")
    else:
        st.info("File `documenti_corpus.jsonl` non trovato. Esegui `analyze_albo.py`.")

elif page == "Dettaglio Documento":
    st.header("Esplorazione Dettagliata del Documento")

    if df_metadati is None:
        st.warning("Impossibile caricare i metadati. Assicurati che `albo_metadati.csv` esista.")
    else:
        # Crea un identificatore unico per la selezione
        df_metadati['display_name'] = df_metadati['file_name'] + " - " + df_metadati['title'].fillna('')

        selected_doc_display = st.selectbox(
            "Seleziona un documento per visualizzare i dettagli:",
            options=df_metadati['display_name'].tolist()
        )

        if selected_doc_display:
            selected_doc_meta = df_metadati[df_metadati['display_name'] == selected_doc_display].iloc[0]
            file_id = selected_doc_meta['file_name'] # Si assume che file_name sia l'ID per i file di testo

            st.subheader(f"Dettagli per: {selected_doc_meta['title']}")

            st.write("---")
            st.markdown("**Metadati di Scraping:**")
            st.json(selected_doc_meta.drop('display_name').to_dict())

            if df_parsed is not None:
                parsed_data = df_parsed[df_parsed['file_name'] == file_id]
                if not parsed_data.empty:
                    st.write("---")
                    st.markdown("**Dati Estratti (`allegati_parsed.csv`):**")
                    st.json(parsed_data.iloc[0].to_dict())
                else:
                    st.info("Nessun dato estratto trovato per questo documento in `allegati_parsed.csv`.")

            if df_features is not None:
                features_data = df_features[df_features['file_name'] == file_id]
                if not features_data.empty:
                    st.write("---")
                    st.markdown("**Feature Analitiche (`documenti_features.csv`):**")
                    st.json(features_data.iloc[0].to_dict())
                else:
                    st.info("Nessuna feature analitica trovata per questo documento in `documenti_features.csv`.")

            st.write("---")
            st.markdown("**Testo Grezzo Estratto dal PDF:**")
            raw_text = get_raw_text(file_id)
            st.text_area("Contenuto del file .txt", raw_text, height=500)

elif page == "Strategia di Comprensione":
    st.header("La Strategia di Comprensione dei PDF")
    st.markdown("""
    La comprensione dei PDF in questo progetto si basa su una pipeline articolata che combina
    estrazione testuale, normalizzazione linguistica e analisi semantica, come descritto nel documento di analisi.
    """)

    st.subheader("1. Estrazione del Testo")
    st.markdown("""
    I documenti PDF vengono processati per estrarre il testo. Questo include la gestione di:
    - **PDF nativi**: testo direttamente estraibile.
    - **PDF scannerizzati (immagini)**: utilizzo di OCR (Tesseract) per convertire l'immagine in testo.
    - **File .p7m (firme digitali)**: decapsulamento della busta crittografica per accedere al contenuto originale (PDF o XML).
    """)
    st.code("""
# Esempio concettuale di estrazione testo (come discusso nel documento di analisi)
# using System.Security.Cryptography.Pkcs;
# public static byte ExtractContent(byte p7mBytes) { ... }
# Poi estrazione testo da PDF/XML risultante.
    """)
    st.markdown("""
    Il testo grezzo estratto viene salvato nella directory `albo_download/texts/`.
    """)

    st.subheader("2. Normalizzazione Linguistica e Analisi Semantica (FST)")
    st.markdown("""
    Una volta estratto il testo, la libreria FST (Finite State Transducers) viene utilizzata
    per la normalizzazione linguistica e la rimozione di ambiguità. Questo è cruciale per
    uniformare la terminologia burocratica italiana (es. "Delibera di G.C.", "Delibera di Giunta Comunale").
    """)
    st.latex(r"""
    \text{transizione} = (q_s, i, o, q_t)
    """)
    st.markdown(r"""
    Dove:
    - \(q_s\): stato di partenza
    - \(i\): carattere o token di input (es. un'abbreviazione burocratica)
    - \(o\): valore canonizzato di output (il termine normalizzato)
    - \(q_t\): stato di arrivo

    Questo processo riduce drasticamente l'ambiguità prima dell'indicizzazione per la ricerca full-text.
    """)

    st.subheader("3. Estrazione di Campi Strutturati")
    st.markdown("""
    `analyze_albo.py` utilizza regole e selettori (potenzialmente dinamici tramite SSharp)
    per estrarre campi specifici dai documenti, come:
    - Oggetto della delibera
    - Date (pubblicazione, esecutività)
    - Riferimenti normativi (es. TUEL, D.Lgs.)
    - Importi economici (CIG, CUP, spese)
    - Nomi di enti o persone
    Questi campi vengono poi strutturati in `allegati_parsed.csv` e `documenti_features.csv`.
    """)

    st.subheader("4. Deduplicazione e Indicizzazione")
    st.markdown("""
    Per evitare ridondanze, viene calcolato un hash SHA-256 per ogni documento.
    Solo i metadati vengono aggiornati se un documento è un duplicato.
    Il testo normalizzato e i campi estratti vengono indicizzati per una ricerca full-text
    ad alte prestazioni, spesso basata su una variante del punteggio TF-IDF.
    """)
    st.latex(r"""
    \text{TF-IDF}(t, d, D) = \text{TF}(t, d) \times \text{IDF}(t, D)
    """)
    st.markdown(r"""
    Dove:
    - \(\text{TF}(t, d)\): frequenza del termine \(t\) nel documento \(d\).
    - \(\text{IDF}(t, D)\): logaritmo inverso della frequenza del documento per il termine \(t\) nell'intero corpus \(D\).
    """)

elif page == "Integrazione Modelli":
    st.header("Integrazione di Modelli Machine Learning")
    st.markdown("""
    Il progetto prevede la possibilità di addestrare e utilizzare modelli di Machine Learning
    (es. tramite `randomForest.py`) per arricchire l'analisi dei documenti.
    """)

    st.subheader("Come i modelli possono essere utilizzati:")
    st.markdown("""
    1.  **Classificazione Automatica**: Classificare le delibere per tipologia (es. "Delibera di Giunta", "Determinazione Dirigenziale", "Piano Urbanistico")
        o per ambito tematico (es. "Tributi", "Lavori Pubblici", "Personale").
        Un modello addestrato potrebbe assegnare automaticamente queste etichette, migliorando la ricercabilità.
    2.  **Estrazione di Entità Nominate (NER)**: Identificare e categorizzare entità specifiche nel testo,
        come nomi di persone, organizzazioni, date, importi, riferimenti normativi, che potrebbero non essere
        catturati dalle regole di parsing fisse.
    3.  **Rilevamento di Anomalie**: Segnalare documenti che presentano pattern insoliti o che deviano
        da standard attesi, potenzialmente indicando errori o non conformità.
    4.  **Raggruppamento (Clustering)**: Raggruppare documenti simili per facilitare l'esplorazione
        di grandi archivi senza etichette predefinite.
    """)

    st.subheader("Caricamento e Utilizzo di un Modello (Esempio Concettuale)")
    st.markdown("""
    Se un modello (es. un `RandomForestClassifier` o un modello di NLP) fosse stato addestrato e salvato
    (ad esempio, in formato `.pkl` o `.joblib`), potrebbe essere caricato qui.
    """)
    st.code("""
# Esempio concettuale di caricamento modello
# import joblib
# model_path = "albo_download/models/my_classifier_model.pkl" # Percorso ipotetico
# if os.path.exists(model_path):
#     my_model = joblib.load(model_path)
#     st.success("Modello caricato con successo!")
#     # Qui si potrebbe aggiungere un'interfaccia per fare previsioni
#     # o visualizzare le performance del modello.
# else:
#     st.info("Nessun modello ML trovato. Esegui `randomForest.py` per addestrarne uno.")
    """)
    st.markdown("""
    I risultati delle previsioni del modello (es. la categoria assegnata a una delibera)
    potrebbero essere aggiunti come nuove colonne in `documenti_features.csv` o `allegati_parsed.csv`
    e visualizzati nella sezione "Dettaglio Documento".
    """)

st.sidebar.markdown("---")
st.sidebar.markdown("Powered by Gemini Code Assist")
