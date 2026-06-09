import pandas as pd
import google.generativeai as genai
import os
import json
import time
from pathlib import Path

# Configura la tua API Key (assicurati di averla in .env o nelle variabili d'ambiente)
# Inserisci qui la tua chiave se non usi le variabili d'ambiente
API_KEY = os.environ.get("GEMINI_API_KEY", "INSERISCI_QUI_LA_TUA_API_KEY")
genai.configure(api_key=API_KEY)

BASE_DIR = Path(r"c:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download")
CSV_PATH = BASE_DIR / "allegati_parsed.csv"
OUTPUT_PATH = BASE_DIR / "allegati_risolti_llm.csv"

def ask_llm_to_classify(text):
    """Sottopone il testo del documento al LLM per la classificazione."""
    prompt = f"""
    Sei un assistente esperto in documenti della Pubblica Amministrazione italiana.
    Leggi il seguente estratto di un atto comunale, classificalo ed estrai le informazioni chiave.
    
    Restituisci ESCLUSIVAMENTE un JSON valido con le seguenti chiavi:
    - "doc_type": (es. Decreto, Ordinanza, Delibera, Avviso, ecc.)
    - "category": (es. Ambiente, Servizi Demografici, Contenzioso, Lavori Pubblici, ecc.)
    - "subcategory": (eventuale sottocategoria utile, o stringa vuota se non applicabile)
    - "beneficiario": (SOLO nome o denominazione della ditta/persona fornitrice o beneficiaria, oppure null se non chiaro o non presente)
    - "importo_max": (il valore numerico dell'importo totale o maggiore in euro espresso come float, es. 1234.56, oppure null se non presente)
    
    Testo del documento:
    {text[:4000]}  # Limitiamo ai primi 4000 caratteri per efficienza
    """
    
    try:
        # Utilizziamo un modello rapido ed economico
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        
        result_text = response.text.strip()
        # Pulizia della risposta per estrarre solo il JSON (se il LLM aggiunge markdown)
        if result_text.startswith("```json"):
            result_text = result_text[7:-3].strip()
        elif result_text.startswith("```"):
            result_text = result_text[3:-3].strip()
            
        data = json.loads(result_text)
        return data
    except Exception as e:
        print(f"Errore durante la chiamata al LLM: {e}")
        return None

def main():
    print(f"Caricamento dati da {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH)
    
    # Filtra i documenti ambigui o non classificati
    ambiguous_mask = (df['classification_confidence'] == 'ambiguous') | (df['doc_type'] == 'unknown') | (df['doc_type'].isna())
    df_ambiguous = df[ambiguous_mask]
    
    print(f"Trovati {len(df_ambiguous)} documenti ambigui/sconosciuti da far revisionare al LLM.")
    
    for index, row in df_ambiguous.iterrows():
        print(f"\nAnalisi documento: {row['pdf_name']}...")
        
        # Usiamo text_preview (oppure puoi aprire il file da row['text_path'])
        text_to_analyze = str(row['text_preview'])
        
        llm_result = ask_llm_to_classify(text_to_analyze)
        
        if llm_result:
            print(f"  -> Risultato LLM: {llm_result}")
            # Aggiorna il dataframe con i dati "intelligenti"
            df.at[index, 'doc_type'] = llm_result.get('doc_type', row['doc_type'])
            df.at[index, 'category'] = llm_result.get('category', row['category'])
            df.at[index, 'subcategory'] = llm_result.get('subcategory', row['subcategory'])
            
            # Integriamo beneficiario e importo solo se la regex aveva fallito (valore nullo nel CSV)
            if pd.isna(row.get('beneficiario')) and llm_result.get('beneficiario'):
                df.at[index, 'beneficiario'] = llm_result['beneficiario']
                
            if pd.isna(row.get('importo_max')) and llm_result.get('importo_max') is not None:
                try:
                    df.at[index, 'importo_max'] = float(llm_result['importo_max'])
                except (ValueError, TypeError):
                    pass

            df.at[index, 'classification_confidence'] = 'llm_resolved'
        
        time.sleep(1) # Pausa cautelativa per rispettare i limiti API (Rate limit)
        
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nProcesso completato. Dati salvati in {OUTPUT_PATH}")

if __name__ == "__main__":
    main()