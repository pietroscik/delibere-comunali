import streamlit as st
import pandas as pd
from pathlib import Path

# Configurazione della pagina
st.set_page_config(page_title="Validazione Albo AI", layout="wide", page_icon="📊")

@st.cache_data
def load_data():
    """Carica i dati dal CSV in modo efficiente."""
    csv_path = Path("albo_download/allegati_parsed.csv")
    if not csv_path.exists():
        return None
    return pd.read_csv(csv_path)

st.title("📊 Validazione Estrazioni AI - Albo Pretorio")
st.markdown("Usa questa dashboard per verificare la qualità dell'estrazione effettuata da Gemini sulle determine e le delibere.")

df = load_data()

if df is None:
    st.error("File 'albo_download/allegati_parsed.csv' non trovato. Assicurati di aver eseguito analyze_albo.py con successo.")
    st.stop()

# --- SEZIONE KPI (Metriche in evidenza) ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Totale Documenti Elaborati", len(df))
col2.metric("Documenti con CIG", df['cig'].notna().sum())
col3.metric("Documenti con Importo", df['importo_max'].notna().sum())
col4.metric("Documenti con Beneficiario", df['beneficiario'].notna().sum())

st.divider()

# --- SEZIONE TABELLA INTERATTIVA ---
st.subheader("🗂️ Vista Tabellare Globale")
st.markdown("Puoi ordinare le colonne cliccando sulle intestazioni, oppure cercare un valore specifico usando l'icona della lente d'ingrandimento sulla tabella.")

# Selezioniamo solo le colonne più utili per la validazione umana
cols_to_show = ['pdf_name', 'doc_type', 'oggetto', 'cig', 'cup', 'importo_max', 'beneficiario', 'responsabile']
available_cols = [c for c in cols_to_show if c in df.columns]

st.dataframe(df[available_cols], use_container_width=True, hide_index=True)

st.divider()

# --- SEZIONE ISPEZIONE DI DETTAGLIO ---
st.subheader("🔍 Ispeziona Singolo Documento (AI vs Testo Reale)")
selected_pdf = st.selectbox("Scegli un documento dal menu a tendina per confrontare l'estrazione con il testo:", df['pdf_name'].tolist())

if selected_pdf:
    doc_data = df[df['pdf_name'] == selected_pdf].iloc[0]
    
    c1, c2 = st.columns([1, 1])
    with c1:
        st.success("**Dati Estratti (Output AI / Regex)**")
        # Mostriamo i dati come dizionario JSON per massima leggibilità
        st.json({
            "Oggetto": doc_data.get('oggetto'),
            "CIG": doc_data.get('cig'),
            "CUP": doc_data.get('cup'),
            "Importo Massimo": f"€ {doc_data.get('importo_max')}" if pd.notna(doc_data.get('importo_max')) else "Nessuno",
            "Beneficiario": doc_data.get('beneficiario'),
            "Responsabile": doc_data.get('responsabile')
        })
    with c2:
        st.info("**Testo Originale Letto dal Parser (Prime 1200 battute)**")
        st.text(doc_data.get('text_preview', 'Testo non disponibile'))