#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script per la pulizia del testo estratto dai documenti PDF.
Rimuove intestazioni ricorrenti, piè di pagina, e certificazioni burocratiche standard
per migliorare la qualità dell'analisi NLP e le risposte del sistema RAG.
"""

import argparse
import json
import re
from pathlib import Path

PATTERNS_TO_REMOVE = [
    # Intestazioni Avella
    r"COPIA Piazza Municipio[^\n]*?http://www\.comune\.avella\.av\.it\.",
    r"Piazza Municipio Avella \(AV\)[^\n]*?utc\.avella@cert\.it",
    r"COMUNE DI AVELLA \(Provincia di Avellino\) Città d'Arte",
    r"COPIA Piazza Municipio I, 83021 Avella \(AV\); P\. IVA n\. 00248800641; Tel\. 081\.8259311; Fax 081\.8259315; PEC comune\.avella@cert\.irpinianet\.eu; http://www\.comune\.avella\.av\.it\.",
    
    # Intestazioni di protocollo
    r"COMUNE DI AVELLA - ACL8JP1 - REG_UFF_PROT.*?Ingresso - \d{2}/\d{2}/\d{4} - \d{2}:\d{2}",
    r"COPIA CONFORME ALL'ORIGINALE DIGITALE Protocollo N\.\d+/\d{4} del \d{2}/\d{2}/\d{4} Firmatario:[^\n]*",
    r"Registro Generale N\.\s*\d+\s*DEL\s*\d{2}/\d{2}/\d{4}",
    r"L'anno duemilaventisei, il giorno \w+, del mese di \w+ nel proprio Ufficio\.",
    r"DETERMINAZIONE DEL RESPONSABILE DEL SERVIZIO N\.\s*\d+\s*DEL\s*\d{2}/\d{2}/\d{4}",

    # Certificazioni e formule di rito (usiamo il lookahead o limiti stringenti)
    r"PARERE DI REGOLARIT[ÀA][']? TECNICA.*?correttezza dell’azione amministrativa\.(?:\s*Esito:\s*Favorevole\s*Note:?)?",
    r"VISTO DI REGOLARIT[ÀA][']? CONTABILE.*?copertura finanziaria del presente atto\.(?:\s*Esito:\s*Favorevole\s*Note:?)?",
    r"ATTESTAZIONE DI CONFORMIT[ÀA][']?.*?repertorio generale dell’Ente\.",
    r"CERTIFICATO DI ESECUTIVIT[ÀA][']?.*?Dichiarata immediatamente eseguibile dall'Organo deliberante\.",
    r"IL PRESENTE VERBALE VIENE LETTO, APPROVATO, E SOTTOSCRITTO\.",
    r"Copia conforme all’originale\.",
    r"ATTESTAZIONE DI PUBBLICAZIONE ALL'ALBO PRETORIO INFORMATICO.*?IL RESPONSABILE DELLE PUBBLICAZIONI ALL'ALBO PRETORIO INFORMATICO\s*f\.to[^\n]*",

    # Date e firme ricorrenti a fine documento
    r"Avella \(AV\), \d{2}/\d{2}/\d{4}\s*Il Responsabile[^\n]*?f\.to[^\n]*",
    r"Avella \(AV\), \d{2}/\d{2}/\d{4}\s*Il Segretario[^\n]*?f\.to[^\n]*",
    r"Avella \(AV\), \d{2}/\d{2}/\d{4}\s*SINDACO[^\n]*?f\.to[^\n]*",
    r"Avella \(AV\), \d{2}/\d{2}/\d{4}\s*PRESIDENTE DEL CONSIGLIO[^\n]*?f\.to[^\n]*",
    r"Avella \(AV\), \d{2}/\d{2}/\d{4}\s*Il Responsabile dei Servizi Finanziari[^\n]*?f\.to[^\n]*",
    r"Avella \(AV\), \d{2}/\d{2}/\d{4}\s*Il Segretario Comunale[^\n]*?f\.to[^\n]*",
]

# Precompila le regex ignorando maiuscole/minuscole e permettendo al '.' di matchare i ritorni a capo per i blocchi lunghi
COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in PATTERNS_TO_REMOVE]

def clean_text(text: str) -> str:
    if not text:
        return ""
    
    # Sostituisci i pattern con stringa vuota
    for pattern in COMPILED_PATTERNS:
        text = pattern.sub("", text)
        
    # Pulisci spazi doppi e linee vuote multiple che si vengono a creare rimuovendo i blocchi
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    
    return text.strip()

def process_texts(texts_dir: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_files = list(texts_dir.glob("*.txt"))
    print(f"Pulizia di {len(txt_files)} file di testo in corso...")
    
    for i, file_path in enumerate(txt_files, 1):
        try:
            original_text = file_path.read_text(encoding="utf-8", errors="ignore")
            cleaned_text = clean_text(original_text)
            
            output_path = output_dir / file_path.name
            output_path.write_text(cleaned_text, encoding="utf-8")
        except Exception as e:
            print(f"[ERRORE] Impossibile pulire il file {file_path.name}: {e}")
            
        if i % 100 == 0:
            print(f"Elaborati {i}/{len(txt_files)} file...")

def process_corpus(corpus_path: Path, output_path: Path):
    print(f"\nPulizia del corpus JSONL {corpus_path.name} in corso...")
    cleaned_rows = []
    
    with corpus_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        row = json.loads(line)
        original_text = row.get("text", "")
        
        if original_text:
            cleaned_text = clean_text(original_text)
            row["text"] = cleaned_text
            row["text_preview"] = cleaned_text[:1200]
            # Aggiorna metriche testuali per riflettere il testo pulito
            row["text_chars"] = len(cleaned_text)
            words = re.findall(r"\w+", cleaned_text.lower(), flags=re.UNICODE)
            row["text_words"] = len(words)
            row["unique_words"] = len(set(words))
            
        cleaned_rows.append(row)
            
    with output_path.open("w", encoding="utf-8") as f:
        for row in cleaned_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[OK] Corpus pulito salvato in {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Pulisce il boilerplate burocratico dai testi estratti.")
    parser.add_argument("--base", type=str, default="./albo_download", help="Cartella base con i dati scaricati.")
    args = parser.parse_args()

    base_dir = Path(args.base)
    process_texts(base_dir / "texts", base_dir / "texts")
    process_corpus(base_dir / "documenti_corpus.jsonl", base_dir / "documenti_corpus.jsonl")

if __name__ == "__main__":
    main()