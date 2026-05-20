# -*- coding: utf-8 -*-
"""
Script di debug per l'estrazione di dati da un singolo file PDF.

Questo script permette di testare la funzione `extract_from_pdf` su un file specifico
per analizzare il testo estratto e migliorare le espressioni regolari.
"""
import re
import os
from pathlib import Path
import pandas as pd
import pytesseract
import pypdfium2 as pdfium
import sys
import json
from dotenv import load_dotenv

# --- COPIA ESATTA DELLE FUNZIONI E VARIABILI DA analyze_albo.py ---

load_dotenv()
# Configura Tesseract se su Windows
if sys.platform == "win32":
    tesseract_path = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path

# --- Extractor usando pypdfium2 ---
def extract_text_pdf(path_str: str) -> str:
    """Estrae testo da PDF usando pypdfium2"""
    try:
        pdf = pdfium.PdfDocument(path_str)
        text_parts = []
        for page in pdf:
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            text_parts.append(text)
        return "\n".join(text_parts)
    except Exception:
        return ""


def _render_pdfium_images(path, dpi=300, max_pages=None):
    pdf = pdfium.PdfDocument(str(path))
    n = len(pdf)
    last = n if max_pages is None else min(n, max_pages)
    scale = dpi / 72.0
    for i in range(last):
        page = pdf[i]
        bitmap = page.render(scale=scale, rotation=0)
        yield bitmap.to_pil()  # PIL Image

def ocr_pdf_probe(path: Path, dpi=300, pages=(1,2)):
    txt = []
    try:
        pdf = pdfium.PdfDocument(str(path))
        scale = dpi / 72.0
        for i in range(min(len(pdf), pages[-1])):
            page = pdf[i]
            bitmap = page.render(scale=scale, rotation=0)
            img = bitmap.to_pil()
            txt.append(pytesseract.image_to_string(img, lang="ita+eng"))
    except Exception:
        return "", False
    text = " ".join(" ".join(txt).split())
    good = any(k in text.lower() for k in ["€","euro","cig","cup","impegno","liquidazione","corrispettivo","spesa"])
    return text, good

def ocr_pdf_full(path: Path, dpi=300, max_pages=None):
    parts = []
    try:
        for img in _render_pdfium_images(path, dpi=dpi, max_pages=max_pages):
            parts.append(pytesseract.image_to_string(img, lang="ita+eng"))
    except Exception:
        return ""
    return " ".join(" ".join(parts).split())

# -------- Regex utili --------
RX_SKIP_PATTERNS = {
    'personnel': re.compile(r'\b(trattenimento in servizio|fabbisogno di personale|dotazione organica|assunzioni|concorso pubblico)\b', re.I),
    'regulation': re.compile(r'\b(approvazione.*regolamento|modifica.*regolamento)\b', re.I),
    'accounting_summary': re.compile(r'\b(riaccertamento.*residui|salvaguardia.*equilibri.*bilancio|Accertamenti da re-imputare)\b', re.I),
    'accounting_residues': re.compile(r'\b(Residui attivi|Residui passivi)\b', re.I),
    'commission': re.compile(r'\b(nomina.*commissione|costituzione.*commissione)\b', re.I),
}
RX_EURO = r'€\s*([\d\.,]+)'
RX_EURO_FALLBACK = r'euro\s*([\d\.,]+)'
RX_AMOUNT_LOOSE = r'(?:importo|totale|spesa complessiva|impegno di spesa|per\s+un\s+importo\s+di)\s+€?\s*([\d\.,]+)'
RX_CIG = r'CIG\s*[:\-\s]*([A-Z0-9]{10,15})'
RX_CUP = r'CUP\s*[:\-\s]*([A-Z0-9]{15})'
RX_BENEF = [
    # Pattern più specifici e affidabili vengono provati prima
    r'Denominazione:\s+([A-Z\s\.\'’\-]+)',
    r'ditta\s+([A-Z\s\.\'’]+(?:S\.R\.L\.|S\.A\.S\.|S\.P\.A\.|COOPERATIVA|srl|sas|spa))',
    r'a\s+favore\s+di\s+([A-Z\s\.\'’]+(?:S\.R\.L\.|S\.A\.S\.|S\.P\.A\.|COOPERATIVA|srl|sas|spa))',
    # Pattern più generici e rischiosi vengono provati per ultimi
    r'liquidare\s+alla\s+ditta\s+([A-Z\s\.\'’]+)',
    r'emessa\s+da\s+([A-Z\s\.\'’]+)',
    r'operatore\s+economico\s+([A-Z\s\.\'’]+)',
]
RX_IMPEGNO = r'(?:impegno|impegno\s+n\.|N\.\s+Impegno\s+Definitivo)\s*[:\s]*(\d+)'
RX_ACCERT = r'(?:accertamento|accertamento\s+n\.|N\.\s+Accertamento)\s*[:\s]*(\d+)'
RX_CAPITOLO = r'(?:capitolo|Capitolo\s+Quinti\s+Livello)\s*[:\s]*([\d\.]+)'
RX_PEG     = re.compile(r"\b(PEG|missione|programma)\b[^\n\r]*", re.I)

def normalize_amount(txt):
    if not txt: return None
    s = txt.strip().replace(" ", "").replace("'", "")
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        if "," in s and "." not in s:
            s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def extract_from_pdf(path: Path) -> dict:

    """Estrae testo e cattura campi principali da un PDF con una logica di estrazione condizionale."""

    out = {

        "pdf_name": path.name,

        "pdf_path": str(path),

        "doc_type": "unknown",

        "importi_raw": [],

        "importo_max": None,

        "cig": None,

        "cup": None,

        "beneficiario": None,

        "impegno_num": None,

        "impegno_anno": None,

        "accert_num": None,

        "accert_anno": None,

        "capitolo": None,

        "peg_riga": None,

        "is_visto_contabile": ("VistoContabile" in path.name),

        "source": "text",

        "extracted_text": "" # Aggiunto per il debug

    }



    # 1. Estrazione del testo (come prima)

    try:

        txt_raw = extract_text_pdf(str(path)) or ""

    except Exception:

        txt_raw = ""



    text_one = " ".join((txt_raw or "").split())



    if len(text_one) < 500:

        probe_txt, good = ocr_pdf_probe(path, dpi=300, pages=(1,2))

        if good or len(probe_txt) > len(text_one):

            full_txt = ocr_pdf_full(path, dpi=300)

            if len(full_txt) > len(text_one):

                text_one = full_txt

                out["source"] = "ocr"

    

    text_one = text_one.replace('\ufffe', ' ').replace('\uf002', ' ')

    out["extracted_text"] = text_one



    # 2. Estrazione dati universali (es. importi) - ESEGUITA SEMPRE

    amts = []

    RX_AMOUNT_TABLE = r'\b(\d{1,3}(?:\.\d{3})*,\d{2})\b'

    for m in re.finditer(RX_EURO, text_one):

        amts.append(m.group(1))

    for m in re.finditer(RX_AMOUNT_LOOSE, text_one): 

        amts.append(m.group(1))

    for m in re.finditer(RX_EURO_FALLBACK, text_one):

        amts.append(m.group(1))

    for m in re.finditer(RX_AMOUNT_TABLE, text_one):

        amts.append(m.group(1))

    

    amts_norm = [normalize_amount(a) for a in amts if normalize_amount(a) is not None]

    out["importi_raw"] = amts

    out["importo_max"] = max(amts_norm) if amts_norm else None



    # 3. Classificazione del documento

    doc_type_found = "transactional"  # Imposta 'transactional' come default

    for doc_type, pattern in RX_SKIP_PATTERNS.items():

        if pattern.search(text_one):

            doc_type_found = doc_type

            break

    out["doc_type"] = doc_type_found



    # 4. Estrazione dati specifici (solo se il documento è transazionale)

    if out["doc_type"] == "transactional":

        m = re.search(RX_CIG, text_one, re.IGNORECASE)

        if m: out["cig"] = m.group(1).upper()

        m = re.search(RX_CUP, text_one, re.IGNORECASE)

        if m: out["cup"] = m.group(1).upper()



        for rx_pattern in RX_BENEF:

            m = re.search(rx_pattern, text_one, re.IGNORECASE)

            if m:

                beneficiario_text = m.group(1).strip(" :;-|")

                beneficiario_text = re.sub(r'\s*-\s*Progressivo Fornitore.*', '', beneficiario_text, flags=re.IGNORECASE)

                if len(beneficiario_text) < 75:

                    out["beneficiario"] = beneficiario_text.strip()

                    break

    

    # 5. Estrazione dati contabili (possono essere presenti in più tipi di documenti)

    m = re.search(RX_IMPEGNO, text_one, re.IGNORECASE)

    if m:

        out["impegno_num"]  = m.group(1)

        if len(m.groups()) > 1 and m.group(2):

            out["impegno_anno"] = m.group(2)

            

    m = re.search(RX_ACCERT, text_one, re.IGNORECASE)

    if m:

        out["accert_num"]  = m.group(1)

        if len(m.groups()) > 1 and m.group(2):

            out["accert_anno"] = m.group(2)

        

    m = re.search(RX_CAPITOLO, text_one, re.IGNORECASE)

    if m:

        out["capitolo"] = m.group(1)

        

    m = RX_PEG.search(text_one)

    if m:

        out["peg_riga"] = m.group(0)



    return out

# --- SCRIPT DI DEBUG ---
if __name__ == "__main__":
    # --- CONFIGURAZIONE ---
    # Incolla qui il nome del file PDF problematico
    PDF_NAME_TO_DEBUG = "atto_1182011__Vai_5.php"
    
    BASE_DIR = Path("albo_download")
    PDF_DIR = BASE_DIR / "pdf"
    
    # --- ESECUZIONE ---
    target_file = PDF_DIR / PDF_NAME_TO_DEBUG
    
    if not target_file.exists():
        print(f"ERRORE: Il file non è stato trovato in '{target_file}'")
        sys.exit(1)
        
    print(f"--- Analisi del file: {target_file.name} ---")
    
    # Esegui l'estrazione
    extracted_data = extract_from_pdf(target_file)
    
    # Stampa i risultati
    print("\n--- TESTO ESTRATTO ---")
    print(extracted_data["extracted_text"])
    print("--- FINE TESTO ESTRATTO ---")
    
    # Rimuovi il testo lungo per una visualizzazione pulita del dizionario
    del extracted_data["extracted_text"]
    
    print("\n--- DATI ESTRATTI ---")
    print(json.dumps(extracted_data, indent=2, ensure_ascii=False))
    print("--- FINE DATI ESTRATTI ---")

    # Analisi specifica del problema
    print("\n--- ANALISI DEL PROBLEMA SPECIFICO ---")
    if extracted_data.get("beneficiario") and len(extracted_data["beneficiario"]) > 100:
        print("[!] Problema rilevato: Il 'beneficiario' estratto è molto lungo, probabilmente è un errore.")
        print(f"    Beneficiario estratto: '{extracted_data['beneficiario']}'")
    elif not extracted_data.get("beneficiario"):
        print("[!] Problema rilevato: Nessun 'beneficiario' è stato estratto.")
    else:
        print("[OK] 'beneficiario' sembra corretto: ", extracted_data.get("beneficiario"))

    if not extracted_data.get("importo_max"):
        print("[!] Problema rilevato: Nessun 'importo_max' è stato estratto.")
    else:
        print("[OK] 'importo_max' estratto: ", extracted_data.get("importo_max"))
