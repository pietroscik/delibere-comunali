import argparse
import pandas as pd
import re

def apply_corrections(metadati_path: str, validation_path: str):
    print(f"Lettura file di validazione: {validation_path}")
    df_val = pd.read_csv(validation_path)
    df_meta = pd.read_csv(metadati_path)

    corrections_applied = 0

    for _, row in df_val.iterrows():
        # Se la tipologia ha una confidenza bassa e c'è un suggerimento
        if row['tipologia_confidence'] < 0.7 and pd.notna(row['suggestions']):
            # Cerca nel testo dei suggerimenti il fallback di filename o oggetto
            m_file = re.search(r"filename=([a-zA-Z]+)", str(row['suggestions']))
            m_ogg = re.search(r"oggetto=([a-zA-Z]+)", str(row['suggestions']))
            
            fallback = None
            if m_file and m_file.group(1) != "None":
                fallback = m_file.group(1)
            elif m_ogg and m_ogg.group(1) != "None":
                fallback = m_ogg.group(1)
            
            if fallback:
                # Applica la correzione in albo_metadati
                url = row['url']
                meta_idx = df_meta.index[df_meta['page_url'] == url]
                if not meta_idx.empty:
                    df_meta.loc[meta_idx, 'tipologia'] = fallback
                    corrections_applied += 1

    if corrections_applied > 0:
        df_meta.to_csv(metadati_path, index=False)
        print(f"✅ Applicate con successo {corrections_applied} correzioni a {metadati_path}.")
    else:
        print("ℹ️ Nessuna correzione automatica necessaria o disponibile.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Applica le correzioni suggerite ai metadati.")
    parser.add_argument("--metadati", default="albo_download/albo_metadati.csv", help="Percorso di albo_metadati.csv")
    parser.add_argument("--validation", default="albo_download/validation_report.csv", help="Percorso di validation_report.csv")
    args = parser.parse_args()
    apply_corrections(args.metadati, args.validation)