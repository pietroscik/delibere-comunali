import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from imblearn.pipeline import Pipeline as ImbPipeline
from imblearn.over_sampling import RandomOverSampler
import joblib
import os

# 1. Caricamento del dataset
script_dir = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(script_dir, 'documenti_features.csv')
allegati_path = os.path.join(script_dir, 'allegati_parsed.csv')

df_features = pd.read_csv(file_path)
try:
    df_allegati = pd.read_csv(allegati_path)
except FileNotFoundError:
    raise FileNotFoundError(f"File non trovato: {allegati_path}. Assicurati che esista per recuperare i testi.")

# Uniamo i due dataset usando 'pdf_name'
if 'pdf_name' in df_features.columns and 'pdf_name' in df_allegati.columns:
    # how='inner' mantiene solo i documenti presenti in entrambi i file
    df = pd.merge(df_features, df_allegati, on='pdf_name', how='inner', suffixes=('', '_allegati'))
else:
    raise ValueError("Colonna 'pdf_name' non trovata per effettuare il merge.")

# Debug: stampiamo le colonne disponibili dopo l'unione
print(f"Colonne presenti nel dataset unito: {df.columns.tolist()}\n")

# Gestione dinamica del nome della colonna di testo
text_column = None
for col in ['text_preview', 'extracted_text', 'text', 'testo', 'text_preview_allegati', 'extracted_text_allegati']:
    if col in df.columns:
        text_column = col
        break

if not text_column:
    raise ValueError(f"ERRORE: Nessuna colonna di testo trovata nel dataset unito.")

# Rimuoviamo eventuali righe con testo o categoria nulli per evitare errori
df = df.dropna(subset=[text_column, 'category'])

# 2. Selezione dei dati per l'addestramento e la valutazione
# Filtriamo SOLO i documenti classificati con "high" confidence dalle tue regex
high_conf_df = df[df['classification_confidence'] == 'high'].copy()

X = high_conf_df[text_column]
y = high_conf_df['category']

# 3. Divisione in Training Set (80%) e Test Set (20%)
# Lo stratify=y assicura che la proporzione delle categorie sia mantenuta in entrambi i set
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# 4. Creazione della Pipeline NLP con Oversampling e Ottimizzazione
pipeline = ImbPipeline([
    # Ottimizzazione: parole singole + bigrammi (es. "lavori pubblici"), scartiamo parole presenti in >80% dei doc (es. "il", "comune") o in <2 doc
    ('tfidf', TfidfVectorizer(max_features=3000, ngram_range=(1, 2), max_df=0.8, min_df=2)), 
    ('oversampler', RandomOverSampler(random_state=42)), # Bilancia le classi minoritarie
    ('clf', RandomForestClassifier(n_estimators=200, random_state=42)) # Raddoppiati gli alberi decisionali
])

# 5. Addestramento del modello
print(f"Addestramento su {len(X_train)} documenti...")
pipeline.fit(X_train, y_train)

# 6. Valutazione del modello sul Test Set
print(f"Valutazione su {len(X_test)} documenti...")
y_pred = pipeline.predict(X_test)

accuracy = accuracy_score(y_test, y_pred)
print(f"\n--- RISULTATI DELLA VALUTAZIONE ---")
print(f"Accuracy Globale: {accuracy:.4f}\n")

# Il classification_report calcola Precision, Recall e F1-Score per singola categoria
print("Report Dettagliato (incluso F1-Score):")
print(classification_report(y_test, y_pred, zero_division=0))

# Salvataggio del modello per l'utilizzo in analyze_albo.py
model_path = os.path.join(script_dir, 'random_forest_model.joblib')
joblib.dump(pipeline, model_path)
print(f"\n[OK] Modello salvato con successo in: {model_path}")

# 7. Applicazione del Modello ai Documenti "Ambigui"
# Ora che il modello è validato, lo usiamo per prevedere la categoria dei documenti ambigui
ambiguous_df = df[df['classification_confidence'].isin(['ambiguous', 'unknown'])].copy()

if not ambiguous_df.empty:
    print(f"\n--- RICLASSIFICAZIONE DOCUMENTI AMBIGUI ---")
    print(f"Riclassificazione di {len(ambiguous_df)} documenti in corso...")
    
    # Prevediamo le nuove categorie
    ambiguous_predictions = pipeline.predict(ambiguous_df[text_column])
    ambiguous_df['predicted_category'] = ambiguous_predictions
    
    # Estraiamo la probabilità/confidenza della previsione
    ambiguous_probabilities = pipeline.predict_proba(ambiguous_df[text_column])
    # Prendiamo il valore massimo di probabilità per ogni riga (che corrisponde alla categoria predetta)
    ambiguous_df['predicted_confidence'] = np.max(ambiguous_probabilities, axis=1)
    
    # Manteniamo la nuova categoria solo se il modello è sicuro almeno al 50%
    soglia_confidenza = 0.50
    ambiguous_df['final_category'] = np.where(
        ambiguous_df['predicted_confidence'] >= soglia_confidenza,
        ambiguous_df['predicted_category'],
        'Da_Revisionare_Manualmente'
    )
    
    # Mostriamo un campione del risultato
    print("\nEsempio di nuove classificazioni:")
    print(ambiguous_df[['pdf_name', 'category', 'final_category', 'predicted_confidence']].head(10))
    
    # Salviamo i risultati in un nuovo file CSV
    output_path = os.path.join(script_dir, 'documenti_riclassificati.csv')
    colonne_da_salvare = ['pdf_name', 'category', 'final_category', 'predicted_confidence']
    ambiguous_df[colonne_da_salvare].to_csv(output_path, index=False)
    print(f"\nRisultati salvati con successo in:\n{output_path}")
    
    # --- AGGIORNAMENTO DEL DATASET ORIGINALE ---
    print("\nAggiornamento del dataset originale in corso...")
    # Filtriamo solo le righe in cui il modello è sicuro
    sicuri_df = ambiguous_df[ambiguous_df['final_category'] != 'Da_Revisionare_Manualmente']
    
    # Creiamo un dizionario {pdf_name: nuova_categoria} per una ricerca veloce
    mappa_nuove_categorie = dict(zip(sicuri_df['pdf_name'], sicuri_df['final_category']))
    
    # Aggiorniamo df_features (il dataset originale caricato all'inizio)
    nuove_cat_assegnate = 0
    for i, row in df_features.iterrows():
        pdf = row['pdf_name']
        if pdf in mappa_nuove_categorie:
            df_features.at[i, 'category'] = mappa_nuove_categorie[pdf]
            df_features.at[i, 'classification_confidence'] = 'high_ml' # Indichiamo che è stato risolto dal Machine Learning
            nuove_cat_assegnate += 1
            
    # Salviamo il dataset aggiornato in un nuovo file per non perdere l'originale
    updated_features_path = os.path.join(script_dir, 'documenti_features_updated.csv')
    df_features.to_csv(updated_features_path, index=False)
    
    print(f"Aggiornate con successo {nuove_cat_assegnate} categorie sicure!")
    print(f"Dataset finale pronto e salvato in:\n{updated_features_path}")

else:
    print("\nNessun documento ambiguo trovato.")
