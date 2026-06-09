import argparse
import pandas as pd
from typing import Dict
from validation_utils import (
    calculate_tipologia_confidence,
    calculate_importi_confidence,
    calculate_overall_confidence,
)
from new_albo_scraper import infer_tipologia_from_filename, infer_tipologia_from_oggetto
from analyze_albo import extract_importi

def validate_document(row_meta, row_allegati=None) -> Dict:
    url = row_meta.get("page_url", "")
    filename = str(row_meta.get("page_url", "")).split("/")[-1]
    oggetto = str(row_meta.get("oggetto", ""))
    tipologia = str(row_meta.get("tipologia", ""))
    doc_type_ml = str(row_allegati.get("doc_type", "")) if row_allegati is not None else ""
    category = str(row_allegati.get("category", "")) if row_allegati is not None else ""
    text = str(row_allegati.get("text_preview", "")) if row_allegati is not None else ""
    classification_conf = str(row_allegati.get("classification_confidence", "")) if row_allegati is not None else ""

    tipologia_conf = calculate_tipologia_confidence(tipologia, filename, oggetto, url, doc_type_ml)
    importi = extract_importi(text) if text else []
    importi_conf = calculate_importi_confidence(importi, doc_type_ml, category, len(text))
    overall_conf = calculate_overall_confidence(tipologia_conf, importi_conf, classification_conf)

    suggestions = []
    if tipologia_conf < 0.7:
        suggestions.append(f"Tipologia a bassa confidenza ({tipologia_conf:.2f}). Fallback suggeriti: filename={infer_tipologia_from_filename(filename)}, oggetto={infer_tipologia_from_oggetto(oggetto)}")
    if importi_conf < 0.7 and doc_type_ml in ["Determinazione", "Delibera", "VistoContabile"]:
        suggestions.append(f"Importi mancanti o non validi in doc contabile ({importi_conf:.2f}).")

    return {
        "url": url,
        "tipologia": tipologia,
        "tipologia_confidence": tipologia_conf,
        "importi_count": len(importi),
        "importi_confidence": importi_conf,
        "classification_confidence": classification_conf,
        "overall_confidence": overall_conf,
        "is_valid": overall_conf >= 0.7,
        "suggestions": " | ".join(suggestions),
    }

def validate_fase0(metadati_path: str, allegati_path: str, output_path: str):
    df_meta = pd.read_csv(metadati_path)
    df_allegati = pd.read_csv(allegati_path)
    results = []
    for _, row_meta in df_meta.iterrows():
        matching_allegati = df_allegati[df_allegati["pdf_path"] == row_meta["page_url"]]
        row_allegati = matching_allegati.iloc[0] if not matching_allegati.empty else None
        results.append(validate_document(row_meta, row_allegati))

    df_validation = pd.DataFrame(results)
    df_validation.to_csv(output_path, index=False)
    return df_validation

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadati", required=True)
    parser.add_argument("--allegati", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    validate_fase0(args.metadati, args.allegati, args.output)