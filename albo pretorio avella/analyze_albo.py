# -*- coding: utf-8 -*-
"""
Created on Wed Nov 12 15:29:14 2025

@author: 39329
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import hashlib
import json
import re
import os
import ast
import sys
import shutil
import subprocess
from typing import Optional
from pathlib import Path
from datetime import datetime

import pandas as pd
import pypdfium2 as pdfium
from dateutil import parser as dateparser
import joblib
from dotenv import load_dotenv

try:
    from System.Security.Cryptography.Pkcs import SignedCms, ContentInfo
except ImportError:
    SignedCms = None

# Carica le variabili d'ambiente dal file .env
load_dotenv()

try:
    import pytesseract
except ModuleNotFoundError:
    pytesseract = None

try:
    from google import genai
except ModuleNotFoundError:
    genai = None

# Configura Tesseract se su Windows leggendo il path dal .env se presente, altrimenti default
if pytesseract and sys.platform == "win32":
    tesseract_path = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path

def extract_p7m_content(p7m_path: Path) -> Optional[bytes]:
    """Estrae il contenuto da un file .p7m usando le librerie .NET se disponibili."""
    if SignedCms is None:
        return None
    try:
        p7m_bytes = p7m_path.read_bytes()
        signed_cms = SignedCms()
        signed_cms.Decode(p7m_bytes)
        return signed_cms.ContentInfo.Content
    except Exception as e:
        # Fallback a riga di comando con OpenSSL se disponibile
        if shutil.which("openssl"):
            try:
                return subprocess.check_output(["openssl", "smime", "-decrypt", "-in", str(p7m_path), "-inform", "DER", "-noverify"])
            except Exception:
                pass
        print(f"[WARN] Estrazione .p7m fallita per {p7m_path.name}: {e}")
        return None

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
    except Exception as e:
        print(f"[ERROR] Estrazione testo nativo fallita per {path_str}: {e}")
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

def _enhance_image_for_ocr(img):
    """Migliora il contrasto e converte in scala di grigi per aiutare Tesseract sui file sgranati."""
    from PIL import ImageEnhance, ImageOps
    img = ImageOps.grayscale(img)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    return img

def ocr_pdf_probe(path: Path, dpi=300, pages=(1,2)):
    if pytesseract is None:
        return "", False
    txt = []
    try:
        pdf = pdfium.PdfDocument(str(path))
        scale = dpi / 72.0
        for i in range(min(len(pdf), pages[-1])):
            page = pdf[i]
            bitmap = page.render(scale=scale, rotation=0)
            img = _enhance_image_for_ocr(bitmap.to_pil())
            txt.append(pytesseract.image_to_string(img, lang="ita", config="--psm 4"))
    except Exception as e:
        print(f"[ERROR] Prova OCR fallita per {path}: {e}")
        return "", False
    text = " ".join(" ".join(txt).split())
    good = any(k in text.lower() for k in ["€","euro","cig","cup","impegno","liquidazione","corrispettivo","spesa"])
    return text, good

def ocr_pdf_full(path: Path, dpi=300, max_pages=None):
    if pytesseract is None:
        return ""
    parts = []
    try:
        for img in _render_pdfium_images(path, dpi=dpi, max_pages=max_pages):
            img = _enhance_image_for_ocr(img)
            parts.append(pytesseract.image_to_string(img, lang="ita", config="--psm 4"))
    except Exception as e:
        print(f"[ERROR] OCR completo fallito per {path}: {e}")
        return ""
    return " ".join(" ".join(parts).split())

SCRIPT_DIR = Path(__file__).resolve().parent

# -------- Regex utili --------
# Regex per documenti da saltare
RX_SKIP_PATTERNS = {
    'personnel': re.compile(r'\b(trattenimento in servizio|fabbisogno di personale|dotazione organica|assunzioni|concorso pubblico)\b', re.I),
    'regulation': re.compile(r'\b(approvazione.*regolamento|modifica.*regolamento)\b', re.I),
    'accounting_summary': re.compile(r'\b(riaccertamento.*residui|salvaguardia.*equilibri.*bilancio)\b', re.I),
    'commission': re.compile(r'\b(nomina.*commissione|costituzione.*commissione)\b', re.I),
}

# Regex per trovare l'importo
RX_EURO = r'€\s*([\d\.,]+)'
RX_EURO_FALLBACK = r'euro\s*([\d\.,]+)'
RX_AMOUNT_LOOSE = r'(?:importo|totale|spesa complessiva|impegno di spesa|per\s+un\s+importo\s+di)\s+€?\s*([\d\.,]+)'

# Regex per CIG e CUP (Migliorate per intercettare C.I.G., spaziature, ecc.)
RX_CIG = r'\bC\.?I\.?G\.?[\s:\-]*([A-Z0-9]{10})\b'
RX_CUP = r'\bC\.?U\.?P\.?[\s:\-]*([A-Z0-9]{15})\b'

# Regex per dati specifici dell'atto
RX_OGGETTO = r'OGGETTO:\s*(.+?)(?=\s+(?:Registro\s+Generale\b|L[\'’\s]anno\b|CIG\s*[:\-]|CUP\s*[:\-]|Premess[oa]\b|Vist[oi]\s*(?::|il\b|la\b|i\b|le\b|che\b|l[\'’])|Considerat[oa]\b|Richiamat[oi]\b|Rilevat[oa]\b|Attes[oa]\b|Acquisit[oa]\b|Dato\s+atto\b|Preso\s+atto\b|DELIBERA\b|DETERMINA\b|ORDINA\b|IL\s+RESPONSABILE\b|IL\s+SINDACO\b|LA\s+GIUNTA\b|IL\s+CONSIGLIO\b|PARERE\b)|$)'
RX_NUM_ATTO = r'N\.\s*(\d+)\s*DEL\s*(\d{2}/\d{2}/\d{4})'
RX_REG_GEN = r'Registro Generale\s*N\.\s*(\d+)\s*DEL\s*(\d{2}/\d{2}/\d{4})'

RX_RESPONSABILE = r'IL\s+RESPONSABILE\s+DEL\s+SERVIZIO\s*(?:\n)?\s*(?:Finanziario)?\s*(?:dott\.|dott\.ssa|Avv\.|Ing\.|Arch\.)?\s*([A-Z][a-zà-úA-Z\s\.\'’]+(?:\s[A-Z][a-zà-úA-Z\s\.\'’]+)*)'
RX_UFFICIO = r'(?:Area|Settore|Servizio)\s+([A-Z][a-zà-úA-Z\s]+)'

# Regex per il beneficiario (più robusta)
RX_BENEF = [
    # Pattern più specifici e affidabili vengono provati prima
    r'Denominazione:\s+([A-Z\s\.\'’\-]+)',
]


# Regex per dati contabili
RX_IMPEGNO = r'(?:impegno|impegno\s+n\.|N\.\s+Impegno\s+Definitivo)\s*[:\s]*(\d+)'
RX_ACCERT = r'(?:accertamento|accertamento\s+n\.|N\.\s+Accertamento)\s*[:\s]*(\d+)'
RX_CAPITOLO = r'(?:capitolo|Capitolo\s+Quinti\s+Livello)\s*[:\s]*([\d\.]+)'
RX_PEG     = re.compile(r"\b(PEG|missione|programma)\b[^\n\r]*", re.I)

# --- Classification Rules ---
CATEGORY_RULES = {
    "Pubblicazione e Trasparenza": ["certificato di pubblicazione", "attestazione pubblicazione", "responsabile delle pubblicazioni", "albo pretorio"],
    "Lavori Pubblici": ["lavori pubblici", "progetto esecutivo", "completamento", "manutenzione straordinaria", "opera pubblica", "cantiere"],
    "Personale": ["personale", "assunzioni", "concorso", "selezione", "progressione verticale", "interpello", "trattenimento in servizio", "fabbisogno di personale", "dotazione organica"],
    "Contabilità": ["regolarità contabile", "visto contabile", "impegno di spesa", "liquidazione", "pagamento", "fattura", "capitolo", "accertamento", "residui", "salvaguardia equilibri", "fondo garanzia debiti commerciali", "pagoPA", "pos"],
    "Contenzioso": ["contenzioso", "incarico legale", "patrocinio", "corte di giustizia", "tribunale", "ricorso"],
    "Urbanistica": ["urbanistica", "piano di sviluppo", "recupero urbano", "permesso di costruire", "edilizia"],
    "Servizi Sociali": ["servizi sociali", "assistenza", "contributo economico", "indennità"],
    "Cultura e Turismo": ["cultura", "turismo", "manifestazione", "evento", "spettacolo"],
    "Ambiente": ["ambiente", "ecologia", "rifiuti", "inquinamento"],
    "Commercio": ["commercio", "suap", "attività produttive"],
    "Regolamenti": ["regolamento", "approvazione", "modifica"],
    "Affari Generali": ["affari generali", "protocollo", "archivio", "statuto"],
    "Servizi Demografici": ["servizi demografici", "anagrafe", "stato civile", "elettorale"],
}

SUBCATEGORY_RULES = {
    "Approvazione Progetto": ["approvazione progetto"],
    "Liquidazione": ["liquidazione", "pagamento", "saldo"],
    "Affidamento Incarico": ["affidamento incarico", "conferimento incarico"],
    "Bando": ["bando", "avviso pubblico"],
    "Concorso": ["concorso", "selezione"],
    "Progressione Verticale": ["progressione verticale", "selezione interna"],
    "Riaccertamento Residui": ["riaccertamento residui"],
    "Variazione di Bilancio": ["variazione di bilancio"],
    "Nomina": ["nomina", "costituzione"],
}

def normalize_amount(txt):
    """Converte stringhe tipo '12.345,67' o '12 345,67' in float 12345.67"""
    if not txt: return None
    s = txt.strip().replace(" ", "").replace("'", "")
    # se ha sia . che ,: di solito . come separatore migliaia, , decimali
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        # se solo virgola, usala come decimale
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        # se solo punto: assumilo come decimale (ok)
    try:
        return float(s)
    except Exception:
        return None

def keyword_hits(haystack, keywords):
    hits = []
    if pd.isna(haystack):
        haystack = ""
    else:
        haystack = str(haystack)
    for keyword in keywords:
        if re.search(r'(?<!\w)' + re.escape(keyword) + r'(?!\w)', haystack, re.IGNORECASE):
            hits.append(keyword)
    return hits

def extract_metadata_with_gemini(text: str) -> dict:
    """Usa l'API di Gemini per estrarre in zero-shot i metadati strutturati dal testo."""
    if not genai or not os.environ.get("GOOGLE_API_KEY"):
        return {}
        
    try:
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        
        prompt = """
        Estrai i seguenti metadati dal testo dell'atto amministrativo fornito.
        Rispondi SOLO con un oggetto JSON valido con la seguente struttura:
        {
            "cig": "...", (oppure null se non presente)
            "cup": "...", (oppure null se non presente)
            "importi_raw": ["...", "..."], (lista di stringhe con gli importi in euro trovati)
            "beneficiario": "...", (SOLO nome o denominazione della ditta/persona. NON inserire ASSOLUTAMENTE frasi o premesse giuridiche come "Visto...", "Accertata la competenza...", se non chiaro restituisci null)
            "responsabile": "...", (SOLO Nome e Cognome di persona fisica, NON inserire intere frasi o riferimenti normativi, altrimenti restituisci null)
            "oggetto": "..." (oggetto dell'atto, stringa pulita)
        }
        Testo:
        """ + text[:15000] # Passiamo le prime 15.000 battute per contenere i costi ed evitare limiti di token
        
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        
        raw_text = response.text.strip()
        # Pulizia di eventuali blocchi markdown inseriti dall'LLM
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()
            
        return json.loads(raw_text)
    except Exception as e:
        print(f"[LLM Error] Fallita estrazione con Gemini: {e}")
        return {}

def classify_document(oggetto, text, rf_model=None):
    """Classifica con punteggio, evitando che l'ordine delle categorie decida da solo."""
    oggetto_str = "" if pd.isna(oggetto) else str(oggetto)
    text_str = "" if pd.isna(text) else str(text)
    
    haystacks = [(oggetto_str, 4), (text_str[:3500], 1)]
    scores = {}
    for category, keywords in CATEGORY_RULES.items():
        score = 0
        matched = []
        for haystack, weight in haystacks:
            hits = keyword_hits(haystack, keywords)
            score += len(hits) * weight
            matched.extend(hits)
        if score:
            scores[category] = (score, sorted(set(matched)))

    category = None
    confidence = None
    terms = []

    if scores:
        ranked = sorted(scores.items(), key=lambda item: (-item[1][0], item[0]))
        category = ranked[0][0]
        confidence = "high"
        terms = ranked[0][1][1]
        if len(ranked) > 1 and ranked[0][1][0] == ranked[1][1][0]:
            confidence = "ambiguous"

    # ML Fallback per documenti ambigui o non classificati
    if (category is None or confidence == "ambiguous") and rf_model is not None:
        text_preview = normalize_text_for_ml(text_str)[:1200]
        if len(text_preview) > 50:
            category = rf_model.predict([text_preview])[0]
            confidence = "ml_predicted"
            terms = ["random_forest"]

    subcategory = None
    for sub, sub_keywords in SUBCATEGORY_RULES.items():
        if keyword_hits(oggetto_str + " " + text_str, sub_keywords):
            subcategory = sub
            break
    return category, subcategory, confidence, ",".join(terms) if terms else None

def infer_doc_type(filename, text):
    name = filename.lower()
    head = (text or "")[:2500].lower()
    name_rules = [
        ("VistoContabile", ("vistocontabile", "visto_contabile")),
        ("AttestazionePubblicazione", ("attestazionepubblicazione", "certificatopubblicazione")),
        ("Elenco", ("elencoelettori", "elenco_", "_elenco")),
        ("Ordinanza", ("ordinanza", "ordinanzesindacali")),
        ("Decreto", ("decreto", "decretosindacale")),
        ("Determinazione", ("determina", "determinazione")),
        ("Delibera", ("delibera", "deliberazione")),
        ("Bando", ("bando",)),
        ("Avviso", ("avviso",)),
    ]
    for label, needles in name_rules:
        if any(n in name for n in needles):
            return label

    rules = [
        ("VistoContabile", ("visto di regolarità contabile", "visto di regolarita contabile")),
        ("AttestazionePubblicazione", ("certificato di pubblicazione", "attestazione di pubblicazione")),
        ("Elenco", ("elenco dei cittadini", "elenco elettori")),
        ("Ordinanza", ("ordinanza sindacale", "ordinanza n.")),
        ("Decreto", ("decreto sindacale", "decreto n.")),
        ("Determinazione", ("determina", "determinazione")),
        ("Delibera", ("delibera", "deliberazione")),
        ("Bando", ("bando",)),
        ("Avviso", ("avviso",)),
    ]
    for label, needles in rules:
        if any(n in head for n in needles):
            return label
    return "unknown"

def is_accounting_relevant(text, doc_type, category):
    haystack = (text or "").lower()
    if doc_type in {"Ordinanza", "Decreto", "Elenco", "AttestazionePubblicazione"}:
        return False
    if doc_type == "VistoContabile":
        return True
    markers = [
        "liquidazione", "impegno di spesa", "determina di impegno", "determina di liquidazione",
        "cig", "cup", "fattura", "fornitore", "pagamento", "capitolo",
        "accertamento", "visto contabile", "regolarità contabile", "regolarita contabile",
        "spesa complessiva", "quadro economico", "importo contrattuale",
    ]
    if any(m in haystack for m in markers):
        return True
    if category == "Contabilità" and doc_type == "Determinazione":
        return True
    if doc_type == "Determinazione" and any(m in haystack for m in ("servizio", "lavori", "fornitura")):
        return True
    return False

def normalize_text_for_ml(text):
    """Normalizza solo spazi e caratteri di controllo, senza perdere contenuto utile."""
    if pd.isna(text):
        text = ""
    else:
        text = str(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", text)
    return " ".join(text.split())

def text_features(text):
    text = text or ""
    lower = text.lower()
    words = re.findall(r"\w+", lower, flags=re.UNICODE)
    years = sorted(set(re.findall(r"\b20\d{2}\b", text)))
    return {
        "text_chars": len(text),
        "text_words": len(words),
        "unique_words": len(set(words)),
        "euro_mentions": len(re.findall(r"€| euro\b", lower)),
        "cig_mentions": len(re.findall(r"\bcig\b", lower)),
        "cup_mentions": len(re.findall(r"\bcup\b", lower)),
        "date_mentions": len(re.findall(r"\b\d{1,2}/\d{1,2}/20\d{2}\b", text)),
        "years_mentioned": ",".join(years),
    }


def extract_from_pdf(path: Path, use_llm: bool = False, rf_model=None) -> dict:
    """Estrae testo e cattura campi principali da un PDF (testuale -> OCR fallback)."""
    
    # Gestione preliminare dei file .p7m
    is_p7m = path.name.lower().endswith(".p7m")
    pdf_content_bytes = None
    if is_p7m:
        pdf_content_bytes = extract_p7m_content(path)
        if not pdf_content_bytes:
            return {"pdf_name": path.name, "pdf_path": str(path), "source": "p7m_extraction_failed"}
        # Usiamo i byte estratti come se fossero il file originale
        path_for_parsing = pdf_content_bytes
    else:
        path_for_parsing = str(path)


    out = {
        "pdf_name": path.name,
        "pdf_path": str(path),
        "doc_type": "unknown",
        "category": None,
        "subcategory": None,
        "classification_confidence": None,
        "classification_terms": None,
        "oggetto": None,
        "numero_atto": None,
        "data_atto": None,
        "numero_registro": None,
        "data_registro": None,
        "importi_raw": [],
        "importo_max": None,
        "importo_sum": None,
        "importi_count": 0,
        "cig": None,
        "cup": None,
        "beneficiario": None,
        "responsabile": None,
        "ufficio": None,
        "impegno_num": None,
        "impegno_anno": None,
        "accert_num": None,
        "accert_anno": None,
        "capitolo": None,
        "peg_riga": None,
        "is_visto_contabile": ("VistoContabile" in path.name),
        "source": "text",   # 'text' o 'ocr'
        "accounting_relevant": False,
        "missing_amount_expected": False,
    }

    # 1) tentativo testuale
    try:
        txt_raw = extract_text_pdf(path_for_parsing) or ""
    except Exception:
        txt_raw = ""

    text_one = " ".join((txt_raw or "").split())

    # Soglia: se testo è molto corto, prova OCR
    if len(text_one) < 500:
        probe_txt, good = ocr_pdf_probe(path, dpi=400, pages=(1,2))
        if good or len(probe_txt) > len(text_one):
            full_txt = ocr_pdf_full(path, dpi=400)
            if len(full_txt) > len(text_one):
                text_one = full_txt
                out["source"] = "ocr"

    text_one = normalize_text_for_ml(text_one)
    out["_text"] = text_one
    out["text_sha256"] = hashlib.sha256(text_one.encode("utf-8", errors="ignore")).hexdigest()
    out.update(text_features(text_one))

    # --- Estrazione via LLM (Opzionale) ---
    llm_data = {}
    if use_llm:
        llm_data = extract_metadata_with_gemini(text_one)

    # --- Oggetto, Numero Atto, Registro Generale ---
    if llm_data.get("oggetto"):
        out["oggetto"] = llm_data["oggetto"]
    else:
        m = re.search(RX_OGGETTO, text_one, re.IGNORECASE)
        if m:
            oggetto_estratto = m.group(1).strip()
            # Tronca se troppo lungo
            if len(oggetto_estratto) > 1500:
                oggetto_estratto = oggetto_estratto[:1500] + "..."
            out["oggetto"] = oggetto_estratto
            
    out["doc_type"] = infer_doc_type(path.name, text_one)

    # --- Classificazione ---
    category, subcategory, confidence, terms = classify_document(out["oggetto"], text_one, rf_model=rf_model)
    out["category"] = category
    out["subcategory"] = subcategory
    out["classification_confidence"] = confidence
    out["classification_terms"] = terms
    out["accounting_relevant"] = is_accounting_relevant(text_one, out["doc_type"], out["category"])

    # --- importi ---
    if llm_data.get("importi_raw"):
        amts = llm_data["importi_raw"]
    else:
        amts = []
        for m in re.finditer(RX_EURO, text_one):
            amts.append(m.group(1))
        for m in re.finditer(RX_AMOUNT_LOOSE, text_one): 
            amts.append(m.group(1))
        for m in re.finditer(RX_EURO_FALLBACK, text_one):
            amts.append(m.group(1))
    # (opzionale) cattura importi SENZA simbolo € quando preceduti da parole chiave
    
    amts_norm = []
    for amount_raw in amts:
        normalized = normalize_amount(amount_raw)
        if normalized is not None:
            amts_norm.append(normalized)
    out["importi_raw"] = amts
    out["importo_max"] = max(amts_norm) if amts_norm else None
    out["importo_sum"] = sum(amts_norm) if amts_norm else None
    out["importi_count"] = len(amts_norm)
    out["missing_amount_expected"] = bool(out["accounting_relevant"] and out["doc_type"] != "VistoContabile" and not amts_norm)

    m = re.search(RX_NUM_ATTO, text_one, re.IGNORECASE)
    if m:
        out["numero_atto"] = m.group(1)
        out["data_atto"] = m.group(2)

    m = re.search(RX_REG_GEN, text_one, re.IGNORECASE)
    if m:
        out["numero_registro"] = m.group(1)
        out["data_registro"] = m.group(2)

    # --- CIG / CUP ---
    if llm_data.get("cig"): out["cig"] = llm_data["cig"].upper()
    else:
        m = re.search(RX_CIG, text_one, re.IGNORECASE)
        if m: out["cig"] = m.group(1).upper()
        
    if llm_data.get("cup"): out["cup"] = llm_data["cup"].upper()
    else:
        m = re.search(RX_CUP, text_one, re.IGNORECASE)
        if m: out["cup"] = m.group(1).upper()

    # --- beneficiario/fornitore/aggiudicatario ---
    if llm_data.get("beneficiario"):
        out["beneficiario"] = llm_data["beneficiario"].strip()
    else:
        for rx_pattern in RX_BENEF:
            m = re.search(rx_pattern, text_one, re.IGNORECASE)
            if m:
                beneficiario_text = m.group(1).strip(" :;-|")
                beneficiario_text = re.sub(r'\s*-\s*Progressivo Fornitore.*', '', beneficiario_text, flags=re.IGNORECASE)
                if len(beneficiario_text) < 150:
                    out["beneficiario"] = beneficiario_text.strip()
                    break
    
    # --- Responsabile e Ufficio ---
    if llm_data.get("responsabile"):
        out["responsabile"] = llm_data["responsabile"].strip()
    else:
        m = re.search(RX_RESPONSABILE, text_one, re.IGNORECASE)
        if m:
            out["responsabile"] = m.group(1).strip()
    m = re.search(RX_UFFICIO, text_one, re.IGNORECASE)
    if m:
        out["ufficio"] = m.group(1).strip()

    # --- impegno/accertamento ---
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
        

    # --- capitolo & PEG ---
    m = re.search(RX_CAPITOLO, text_one, re.IGNORECASE)
    if m:
        out["capitolo"] = m.group(1)
    m = RX_PEG.search(text_one)
    if m:
        out["peg_riga"] = m.group(0)

    return out


def safe_literal_list(s):
    """Converte la stringa della colonna allegati (lista) in lista Python."""
    if pd.isna(s) or not str(s).strip():
        return []
    txt = str(s).strip()
    # tentativo con ast.literal_eval (se è una lista python)
    try:
        val = ast.literal_eval(txt)
        if isinstance(val, list):
            return [str(x) for x in val]
    except Exception:
        pass
    # fallback: separatore ; o |
    if ";" in txt:
        return [t.strip() for t in txt.split(";") if t.strip()]
    if "|" in txt:
        return [t.strip() for t in txt.split("|") if t.strip()]
    # ultimo tentativo: singolo URL
    return [txt]

def build_parser():
    ap = argparse.ArgumentParser(description="Analizza gli allegati PDF scaricati dall'albo.")
    ap.add_argument("--base", default=str(SCRIPT_DIR / "albo_download"), help="Cartella output dello scraper.")
    ap.add_argument("--csv", default=None, help="CSV metadati. Default: <base>/albo_metadati.csv")
    ap.add_argument("--pdf-dir", default=None, help="Cartella PDF. Default: <base>/pdf")
    ap.add_argument("--no-corpus", action="store_true", help="Non esportare corpus JSONL e testi per ML/RAG.")
    ap.add_argument("--use-llm", action="store_true", help="Usa Gemini API per estrarre metadati complessi (richiede variabile d'ambiente GOOGLE_API_KEY).")
    return ap

def main():
    args = build_parser().parse_args()
    if pytesseract is None:
        print("[WARN] pytesseract non installato: OCR disattivato, continuo con testo PDF estraibile.")

    base = Path(args.base)
    csv_path = Path(args.csv) if args.csv else base / "albo_metadati.csv"
    pdf_dir = Path(args.pdf_dir) if args.pdf_dir else base / "pdf"
    out_xlsx = base / "albo_analisi.xlsx"
    out_csv_allegati = base / "allegati_parsed.csv"
    out_csv_atti = base / "atti_parsed.csv"
    out_csv_features = base / "documenti_features.csv"
    out_corpus_jsonl = base / "documenti_corpus.jsonl"
    text_dir = base / "texts"

    # Caricamento del modello ML (Random Forest) se esiste
    model_path = base / "random_forest_model.joblib"
    rf_model = None
    if model_path.exists():
        try:
            rf_model = joblib.load(model_path)
            print(f"[OK] Modello Machine Learning caricato da {model_path}")
        except Exception as e:
            print(f"[WARN] Impossibile caricare il modello ML: {e}")

    # 1) Metadati
    df = pd.read_csv(csv_path, encoding="utf-8", sep=",")
    # normalizza colonne attese dallo scraper
    expected = ["page_url","titolo","numero","data_pubblicazione","tipologia","ufficio","oggetto","dettaglio_url","allegati"]
    for c in expected:
        if c not in df.columns: df[c] = None

    # date pulite
    def to_date(x):
        if pd.isna(x) or not str(x).strip():
            return pd.NaT
        try:
            return dateparser.parse(str(x), dayfirst=True)
        except Exception:
            return pd.NaT
    df["data_dt"] = df["data_pubblicazione"].apply(to_date)

    # 2) Esplodi allegati
    df["allegati_list"] = df["allegati"].apply(safe_literal_list)
    rows = []
    for idx, r in df.iterrows():
        for url in r["allegati_list"]:
            rows.append({
                "titolo": r["titolo"],
                "numero": r["numero"],
                "data_pubblicazione": r["data_pubblicazione"],
                "data_dt": r["data_dt"],
                "tipologia": r["tipologia"],
                "ufficio": r["ufficio"],
                "oggetto": r["oggetto"],
                "dettaglio_url": r["dettaglio_url"],
                "allegato_url": url
            })
    dfa = pd.DataFrame(rows)

    # 3) Processa tutti i PDF locali indipendentemente dai metadati
    print("Processando PDF locali...")
    files = list(pdf_dir.glob("*.pdf")) + list(pdf_dir.glob("*.php")) + list(pdf_dir.glob("*.p7m"))
    print(f"Trovati {len(files)} file PDF/PHP")
    
    # Caricamento cache dei PDF già elaborati per evitare chiamate inutili all'API
    processed_cache = {}
    if out_csv_allegati.exists():
        try:
            df_cache = pd.read_csv(out_csv_allegati, encoding="utf-8")
            # Carichiamo i vecchi record in un dizionario con chiave il nome del pdf
            processed_cache = df_cache.set_index('pdf_name').to_dict('index')
            print(f"Trovati {len(processed_cache)} PDF già elaborati nel CSV. Verranno saltati per risparmiare tempo e API.")
        except Exception as e:
            print(f"[WARN] Impossibile caricare la cache dei PDF esistenti: {e}")

    # 4) Parsing PDF
    parsed_pdfs = []
    corpus_rows = []
    for idx, pdf_file in enumerate(files):
        if idx % 10 == 0:
            print(f"Processando {idx}/{len(files)}...")
            
        if pdf_file.name in processed_cache:
            info = processed_cache[pdf_file.name]
            
            # Se abbiamo il modello ML, rivalutiamo al volo i documenti incerti presenti in cache
            if rf_model is not None and info.get("classification_confidence") in (None, "ambiguous", "unknown"):
                cat, sub, conf, terms = classify_document(info.get("oggetto"), info.get("text_preview"), rf_model=rf_model)
                info["category"] = cat
                info["subcategory"] = sub
                info["classification_confidence"] = conf
                info["classification_terms"] = terms
                
            info["pdf_name"] = pdf_file.name # Ripristiniamo la chiave
            parsed_pdfs.append(info)
            
            # Ricostruiamo la riga per il corpus testuale (RAG) leggendo il .txt se la cache l'ha saltato
            if not args.no_corpus:
                text_path_val = info.get("text_path")
                text_path_val = text_path_val if pd.notna(text_path_val) else text_dir / (pdf_file.stem + ".txt")
                text_path = Path(text_path_val)
                text_full = text_path.read_text(encoding="utf-8", errors="ignore") if text_path.exists() else ""
                corpus_rows.append({
                    **info,
                    "text": text_full,
                })
            continue
            
        info = extract_from_pdf(pdf_file, use_llm=args.use_llm, rf_model=rf_model)
        text_full = info.pop("_text", "")
        text_name = pdf_file.stem + ".txt"
        text_path = text_dir / text_name
        info["text_path"] = str(text_path)
        info["text_preview"] = text_full[:1200]
        corpus_rows.append({
            **info,
            "text": text_full,
        })
        parsed_pdfs.append(info)
    
    dfp = pd.DataFrame(parsed_pdfs)
    print(f"\nPDF processati: {len(dfp)}")
    print(f"PDF con OCR: {(dfp['source']=='ocr').sum()}")
    print(f"PDF con testo: {(dfp['source']=='text').sum()}")

    # Statistiche sul tipo di documento
    print("\nStatistiche tipo documento:")
    print(dfp["doc_type"].value_counts())
    
    # Rimuoviamo la pulizia complessa, affidandoci a xlsxwriter
    
    # 6) Costruisci tabella per atto (collapse allegati) - versione semplificata per PDF processati
    # KPI veloci sui PDF trovati
    # Top fornitori per somma importo_max
    fornitori = (dfp.dropna(subset=["beneficiario"])
                    .groupby("beneficiario", dropna=False)["importo_max"]
                    .sum().sort_values(ascending=False).reset_index()
                    .rename(columns={"importo_max":"importo_totale"}))

    # Statistiche base
    kpi_source = dfp.groupby("source", dropna=False)["importo_max"].agg(["count","sum"]).reset_index()
    kpi_visto  = dfp.groupby("is_visto_contabile", dropna=False)["importo_max"].agg(["count","sum"]).reset_index()
    kpi_doctype = dfp.groupby("doc_type", dropna=False)["importo_max"].agg(["count", "sum"]).reset_index()
    feature_cols = [
        "pdf_name", "doc_type", "category", "subcategory", "classification_confidence",
        "source", "text_sha256", "text_chars", "text_words", "unique_words",
        "euro_mentions", "cig", "cup", "cig_mentions", "cup_mentions", "date_mentions",
        "years_mentioned", "importo_max", "importo_sum", "importi_count",
        "accounting_relevant", "missing_amount_expected",
    ]
    dff = dfp[[c for c in feature_cols if c in dfp.columns]].copy()

    # 7) Salva CSV/Excel
    print("\nSalvataggio CSV...")
    dfp.to_csv(out_csv_allegati, index=False, encoding="utf-8")
    dff.to_csv(out_csv_features, index=False, encoding="utf-8")
    if not args.no_corpus:
        text_dir.mkdir(parents=True, exist_ok=True)
        with open(out_corpus_jsonl, "w", encoding="utf-8") as f:
            for row in corpus_rows:
                text_path = Path(row["text_path"])
                text_path.write_text(row["text"], encoding="utf-8", errors="ignore")
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # Per atti, usiamo i dati originali dei metadati se disponibili
    if len(dfa) > 0:
        dfa.to_csv(out_csv_atti, index=False, encoding="utf-8")
    else:
        dfp.to_csv(out_csv_atti, index=False, encoding="utf-8")
    
    print("CSV salvati con successo!")
    print("\nSalvataggio Excel con motore 'xlsxwriter'...")
    
    try:
        with pd.ExcelWriter(out_xlsx, engine="xlsxwriter") as xl:
            dfp.to_excel(xl, index=False, sheet_name="pdf_analisi")
            kpi_source.to_excel(xl, index=False, sheet_name="kpi_source")
            kpi_visto.to_excel(xl, index=False, sheet_name="kpi_visto_contabile")
            kpi_doctype.to_excel(xl, index=False, sheet_name="kpi_doctype")
            dff.to_excel(xl, index=False, sheet_name="features_ml")
            fornitori.head(50).to_excel(xl, index=False, sheet_name="fornitori_top50")
            if len(dfa) > 0:
                dfa.to_excel(xl, index=False, sheet_name="metadati")
            
            # Crea un foglio dedicato per revisionare comodamente le predizioni del modello ML
            ml_preds = dfp[dfp['classification_confidence'] == 'ml_predicted']
            if not ml_preds.empty:
                cols_review = [c for c in ["pdf_name", "doc_type", "category", "oggetto", "text_preview"] if c in dfp.columns]
                ml_preds[cols_review].to_excel(xl, index=False, sheet_name="revisione_ml")
        
        print("Excel salvato con successo!")
    except Exception as e:
        print(f"[WARN] Errore salvataggio Excel con xlsxwriter: {e}")
        print("I dati CSV sono comunque disponibili!")

    print(f"\n[OK] Salvati:\n- {out_csv_allegati}\n- {out_csv_atti}\n- {out_csv_features}\n- {out_corpus_jsonl if not args.no_corpus else '(corpus disattivato)'}\n- {out_xlsx} (se riuscito)")

if __name__ == "__main__":
    main()
