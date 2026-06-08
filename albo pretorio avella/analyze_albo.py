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
import time
import subprocess
from typing import Optional
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import pypdfium2 as pdfium
from dateutil import parser as dateparser
import joblib
from dotenv import load_dotenv

from logger import get_logger
from metrics import get_metrics_collector

logger = get_logger("analyze_albo")
metrics = get_metrics_collector()

try:
    from enhanced_extractor import DelibereExtractor
except ImportError:
    DelibereExtractor = None

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

# Inizializza l'estrattore avanzato globale
advanced_extractor = DelibereExtractor() if DelibereExtractor else None

# Configura Tesseract se su Windows leggendo il path dal .env se presente, altrimenti default
if pytesseract and sys.platform == "win32":
    tesseract_path = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        # Imposta automaticamente TESSDATA_PREFIX se non esiste nell'ambiente
        tessdata_path = os.path.join(os.path.dirname(tesseract_path), "tessdata")
        if "TESSDATA_PREFIX" not in os.environ and os.path.exists(tessdata_path):
            os.environ["TESSDATA_PREFIX"] = tessdata_path

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
        logger.warning(f"Estrazione .p7m fallita per {p7m_path.name}: {e}")
        return None

# --- Extractor usando pypdfium2 ---
def extract_text_pdf(pdf_input) -> str:
    """Estrae testo da PDF usando pypdfium2"""
    try:
        pdf = pdfium.PdfDocument(pdf_input)
        text_parts = []
        for page in pdf:
            textpage = page.get_textpage()
            text = textpage.get_text_bounded()
            text_parts.append(text)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Estrazione testo nativo fallita: {e}")
        return ""


def _render_pdfium_images(pdf_input, dpi=300, max_pages=None):
    try:
        pdf = pdfium.PdfDocument(pdf_input)
    except Exception as e:
        logger.error(f"Render PDF fallito: {e}")
        return
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

def ocr_pdf_probe(pdf_input, dpi=300, pages=(1,2)):
    if pytesseract is None:
        return "", False
    txt = []
    try:
        pdf = pdfium.PdfDocument(pdf_input)
        scale = dpi / 72.0
        for i in range(min(len(pdf), pages[-1])):
            page = pdf[i]
            bitmap = page.render(scale=scale, rotation=0)
            img = _enhance_image_for_ocr(bitmap.to_pil())
            try:
                txt.append(pytesseract.image_to_string(img, lang="ita", config="--psm 4"))
            except pytesseract.TesseractError:
                # Fallback alla lingua inglese (di default sempre presente) se manca l'italiano
                txt.append(pytesseract.image_to_string(img, lang="eng", config="--psm 4"))
    except Exception as e:
        logger.error(f"Prova OCR fallita: {e}")
        return "", False
    text = " ".join(" ".join(txt).split())
    good = any(k in text.lower() for k in ["€","euro","cig","cup","impegno","liquidazione","corrispettivo","spesa"])
    return text, good

def ocr_pdf_full(pdf_input, dpi=300, max_pages=None):
    if pytesseract is None:
        return ""
    parts = []
    try:
        for img in _render_pdfium_images(pdf_input, dpi=dpi, max_pages=max_pages):
            img = _enhance_image_for_ocr(img)
            try:
                parts.append(pytesseract.image_to_string(img, lang="ita", config="--psm 4"))
            except pytesseract.TesseractError:
                parts.append(pytesseract.image_to_string(img, lang="eng", config="--psm 4"))
    except Exception as e:
        logger.error(f"OCR completo fallito: {e}")
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
RX_EURO = re.compile(r'€\s*([\d\.,]+)')
RX_EURO_FALLBACK = re.compile(r'euro\s*([\d\.,]+)', re.IGNORECASE)
RX_AMOUNT_LOOSE = re.compile(r'(?:importo|totale|spesa complessiva|impegno di spesa|per\s+un\s+importo\s+di)\s+€?\s*([\d\.,]+)', re.IGNORECASE)

# Regex per CIG e CUP (Migliorate per intercettare C.I.G., spaziature, ecc.)
RX_CIG = re.compile(r'\bC\.?I\.?G\.?(?:\s*(?:n\.|numero|codice)?\s*[:\-]?\s*)([A-Z0-9]{10})\b', re.IGNORECASE)
RX_CUP = re.compile(r'\bC\.?U\.?P\.?(?:\s*(?:n\.|numero|codice)?\s*[:\-]?\s*)([A-Z0-9]{15})\b', re.IGNORECASE)

# Regex per dati specifici dell'atto
RX_OGGETTO = re.compile(r'OGGETTO:\s*(.+?)(?=\s+(?:Registro\s+Generale\b|L[\'’\s]anno\b|CIG\s*[:\-]|CUP\s*[:\-]|Premess[oa]\b|Vist[oi]\s*(?::|il\b|la\b|i\b|le\b|che\b|l[\'’])|Considerat[oa]\b|Richiamat[oi]\b|Rilevat[oa]\b|Attes[oa]\b|Acquisit[oa]\b|Dato\s+atto\b|Preso\s+atto\b|DELIBERA\b|DETERMINA\b|ORDINA\b|IL\s+RESPONSABILE\b|IL\s+SINDACO\b|LA\s+GIUNTA\b|IL\s+CONSIGLIO\b|PARERE\b)|$)', re.IGNORECASE)
RX_NUM_ATTO = re.compile(r'N\.\s*(\d+)\s*DEL\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
RX_REG_GEN = re.compile(r'Registro Generale\s*N\.\s*(\d+)\s*DEL\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE)

RX_RESPONSABILE = re.compile(r'IL\s+RESPONSABILE\s+DEL\s+SERVIZIO\s*(?:\n)?\s*(?:Finanziario)?\s*(?:dott\.|dott\.ssa|Avv\.|Ing\.|Arch\.)?\s*([A-Z][a-zà-úA-Z\s\.\'’]+(?:\s[A-Z][a-zà-úA-Z\s\.\'’]+)*)', re.IGNORECASE)
RX_UFFICIO = re.compile(r'(?:Area|Settore|Servizio)\s+([A-Z][a-zà-úA-Z\s]+)', re.IGNORECASE)

# Regex per il beneficiario (più robusta)
RX_BENEF = [
    # Pattern più specifici e affidabili vengono provati prima
    re.compile(r'Denominazione:\s+([A-Z\s\.\'’\-]+)', re.IGNORECASE),
]


# Regex per dati contabili
RX_IMPEGNO = re.compile(r'(?:impegno|impegno\s+n\.|N\.\s+Impegno\s+Definitivo)\s*[:\s]*(\d+)', re.IGNORECASE)
RX_ACCERT = re.compile(r'(?:accertamento|accertamento\s+n\.|N\.\s+Accertamento)\s*[:\s]*(\d+)', re.IGNORECASE)
RX_CAPITOLO = re.compile(r'(?:capitolo|Capitolo\s+Quinti\s+Livello)\s*[:\s]*([\d\.]+)', re.IGNORECASE)
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
            model='gemini-2.5-flash',
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
        msg = str(e).lower()
        if "429" in msg or "quota" in msg or "exhausted" in msg:
            logger.warning("[LLM Quota] Limite di chiamate gratuite raggiunto. Il sistema rallenterà automaticamente...")
            time.sleep(20) # Mette in pausa per far resettare il contatore di Google al minuto successivo
        logger.error(f"Fallita estrazione con Gemini: {e}")
        return {}

def extract_quadro_economico_vision(pdf_path: Path) -> dict:
    """Usa Gemini Multimodal (Vision) per estrarre il quadro economico dalle immagini del PDF."""
    if not genai or not os.environ.get("GOOGLE_API_KEY"):
        return {}
        
    try:
        # Renderizziamo solo le prime 3 pagine e le ultime 2 (dove di solito si trovano i quadri economici)
        # per risparmiare token ed evitare di saturare l'API.
        images = list(_render_pdfium_images(pdf_path, dpi=150, max_pages=4))
        if not images:
            return {}

        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        
        prompt = """
        Analizza le immagini di questo atto amministrativo.
        Cerca una tabella relativa al "Quadro Economico", "Riepilogo Spese" o "Computo Metrico".
        Se la trovi, estrai i dati in formato JSON strutturato con un array di voci.
        Rispondi SOLO con un oggetto JSON valido con la seguente struttura:
        {
            "quadro_economico_trovato": true,
            "totale_complessivo": 12345.67,
            "voci": [
                {"descrizione": "Lavori a base d'asta", "importo": 10000.00},
                {"descrizione": "IVA 22%", "importo": 2200.00}
            ]
        }
        Se non trovi nessun quadro economico o tabella di riepilogo, rispondi {"quadro_economico_trovato": false}.
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash', # Modello ottimizzato per compiti multimodali veloci
            contents=[prompt] + images,
            config={'response_mime_type': 'application/json'}
        )
        
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()
            
        return json.loads(raw_text)
    except Exception as e:
        msg = str(e).lower()
        if "429" in msg or "quota" in msg or "exhausted" in msg:
            logger.warning("[Vision Quota] Limite di chiamate gratuite raggiunto. Pausa di sicurezza...")
            time.sleep(20)
        logger.error(f"Fallita estrazione Quadro Economico: {e}")
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
            try:
                max_prob = np.max(rf_model.predict_proba([text_preview]))
                if max_prob >= 0.50:
                    category = rf_model.predict([text_preview])[0]
                    confidence = "ml_predicted"
                    terms = ["random_forest"]
            except Exception as e:
                logger.warning(f"Errore durante la predizione ML: {e}")

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


def extract_from_pdf(path: Path, use_llm: bool = False, rf_model=None, text_dir: Path = None) -> dict:
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
        "piva_beneficiario": None,
        "iban": None,
        "codice_appalti": None,
        "importo_lettere": None,
        "anomalie": None,
        "responsabile": None,
        "ufficio": None,
        "impegno_num": None,
        "impegno_anno": None,
        "accert_num": None,
        "accert_anno": None,
        "quadro_economico": None,
        "capitolo": None,
        "peg_riga": None,
        "is_visto_contabile": ("VistoContabile" in path.name),
        "source": "text",   # 'text' o 'ocr'
        "accounting_relevant": False,
        "missing_amount_expected": False,
    }

    # 1) Verifica se esiste già un file di testo pre-generato (es. dal backend C#)
    text_file_path = text_dir / f"{path.stem}.txt" if text_dir else None
    if text_file_path and text_file_path.exists():
        text_one = text_file_path.read_text(encoding="utf-8", errors="ignore")
        text_one = " ".join(text_one.split())
        out["source"] = "csharp_extracted_text"
    else:
        # 2) Tentativo testuale nativo Python (Fallback)
        try:
            txt_raw = extract_text_pdf(path_for_parsing) or ""
        except Exception:
            txt_raw = ""

        text_one = " ".join((txt_raw or "").split())

        # Soglia: se testo è molto corto, prova OCR
        if len(text_one) < 500:
            probe_txt, good = ocr_pdf_probe(path_for_parsing, dpi=400, pages=(1,2))
            if good or len(probe_txt) > len(text_one):
                full_txt = ocr_pdf_full(path_for_parsing, dpi=400)
                if len(full_txt) > len(text_one):
                    text_one = full_txt
                    out["source"] = "ocr"

    text_one = normalize_text_for_ml(text_one)
    out["_text"] = text_one
    out["text_sha256"] = hashlib.sha256(text_one.encode("utf-8", errors="ignore")).hexdigest()
    out.update(text_features(text_one))

    # --- Estrazione Avanzata (Regex Potenziate) ---
    adv_data = {}
    if advanced_extractor:
        adv_data = advanced_extractor.extract_entities(text_one)

    # --- Estrazione via LLM (Opzionale) ---
    llm_data = {}
    if use_llm:
        llm_data = extract_metadata_with_gemini(text_one)
        
        # Applichiamo la Vision API solo se il documento è di natura contabile o un Lavoro Pubblico
        if out.get("accounting_relevant") or out.get("category") == "Lavori Pubblici":
            vision_data = extract_quadro_economico_vision(path)
            if vision_data.get("quadro_economico_trovato"):
                out["quadro_economico"] = json.dumps(vision_data.get("voci", []), ensure_ascii=False)

    # --- Oggetto, Numero Atto, Registro Generale ---
    if llm_data.get("oggetto"):
        out["oggetto"] = llm_data["oggetto"]
    else:
        m = RX_OGGETTO.search(text_one)
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
        for m in RX_EURO.finditer(text_one):
            amts.append(m.group(1))
        for m in RX_AMOUNT_LOOSE.finditer(text_one): 
            amts.append(m.group(1))
        for m in RX_EURO_FALLBACK.finditer(text_one):
            amts.append(m.group(1))
    # (opzionale) cattura importi SENZA simbolo € quando preceduti da parole chiave
    
    amts_norm = []
    for amount_raw in amts:
        normalized = normalize_amount(amount_raw)
        if normalized is not None:
            amts_norm.append(normalized)
    out["importi_raw"] = amts
    
    # Se l'estrattore avanzato trova un importo, diamogli priorità
    out["importo_max"] = adv_data.get("importo_max_estratto") or (max(amts_norm) if amts_norm else None)
    out["importo_sum"] = sum(amts_norm) if amts_norm else None
    out["importi_count"] = len(amts_norm)
    out["missing_amount_expected"] = bool(out["accounting_relevant"] and out["doc_type"] != "VistoContabile" and not amts_norm)

    m = RX_NUM_ATTO.search(text_one)
    if m:
        out["numero_atto"] = m.group(1)
        out["data_atto"] = m.group(2)

    m = RX_REG_GEN.search(text_one)
    if m:
        out["numero_registro"] = m.group(1)
        out["data_registro"] = m.group(2)

    # --- CIG / CUP ---
    try:
        if llm_data.get("cig"): out["cig"] = llm_data["cig"].upper()
        elif adv_data.get("cig_estratto"): out["cig"] = adv_data["cig_estratto"].upper()
        else:
            m = RX_CIG.search(text_one)
            if m: out["cig"] = m.group(1).upper()
            
        if llm_data.get("cup"): out["cup"] = llm_data["cup"].upper()
        elif adv_data.get("cup_estratto"): out["cup"] = adv_data["cup_estratto"].upper()
        else:
            m = RX_CUP.search(text_one)
            if m: out["cup"] = m.group(1).upper()
    except Exception as e:
        logger.warning(f"Errore durante l'estrazione di CIG/CUP per {path.name}: {e}")

    # --- beneficiario/fornitore/aggiudicatario ---
    if llm_data.get("beneficiario"):
        out["beneficiario"] = llm_data["beneficiario"].strip()
    else:
        for rx_pattern in RX_BENEF:
            m = rx_pattern.search(text_one)
            if m:
                beneficiario_text = m.group(1).strip(" :;-|")
                beneficiario_text = re.sub(r'\s*-\s*Progressivo Fornitore.*', '', beneficiario_text, flags=re.IGNORECASE)
                if len(beneficiario_text) < 150:
                    out["beneficiario"] = beneficiario_text.strip()
                    break
    
    out["piva_beneficiario"] = adv_data.get("piva_beneficiario")
    out["iban"] = adv_data.get("iban_estratto")
    out["codice_appalti"] = adv_data.get("codice_appalti")
    out["importo_lettere"] = adv_data.get("importo_lettere")
    out["anomalie"] = adv_data.get("anomalie_rilevate")

    # --- Responsabile e Ufficio ---
    if llm_data.get("responsabile"):
        out["responsabile"] = llm_data["responsabile"].strip()
    else:
        m = RX_RESPONSABILE.search(text_one)
        if m:
            out["responsabile"] = m.group(1).strip()
    m = RX_UFFICIO.search(text_one)
    if m:
        out["ufficio"] = m.group(1).strip()

    # --- impegno/accertamento ---
    m = RX_IMPEGNO.search(text_one)
    if m:
        out["impegno_num"]  = m.group(1)
        if len(m.groups()) > 1 and m.group(2):
            out["impegno_anno"] = m.group(2)
            
    m = RX_ACCERT.search(text_one)
    if m:
        out["accert_num"]  = m.group(1)
        if len(m.groups()) > 1 and m.group(2):
            out["accert_anno"] = m.group(2)
        

    # --- capitolo & PEG ---
    m = RX_CAPITOLO.search(text_one)
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
        logger.warning("pytesseract non installato: OCR disattivato, continuo con testo PDF estraibile.")

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
            logger.info(f"Modello Machine Learning caricato da {model_path}")
        except Exception as e:
            logger.warning(f"Impossibile caricare il modello ML: {e}")

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
    logger.info("Processando PDF locali...")
    files = list(pdf_dir.glob("*.pdf")) + list(pdf_dir.glob("*.php")) + list(pdf_dir.glob("*.p7m"))
    logger.info(f"Trovati {len(files)} file PDF/PHP")
    
    # Caricamento cache dei PDF già elaborati per evitare chiamate inutili all'API
    processed_cache = {}
    if out_csv_allegati.exists():
        try:
            df_cache = pd.read_csv(out_csv_allegati, encoding="utf-8")
            # Carichiamo i vecchi record in un dizionario con chiave il nome del pdf
            processed_cache = df_cache.set_index('pdf_name').to_dict('index')
            logger.info(f"Trovati {len(processed_cache)} PDF già elaborati nel CSV. Verranno saltati per risparmiare tempo e API.")
        except Exception as e:
            logger.warning(f"Impossibile caricare la cache dei PDF esistenti: {e}")

    # 4) Parsing PDF
    parsed_pdfs = []
    corpus_rows = []
    
    with metrics.start_operation("analisi_pdf") as op:
        for idx, pdf_file in enumerate(files):
            if idx % 10 == 0:
                logger.info(f"Processando {idx}/{len(files)}...")
                
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
        
        op.set_items_processed(len(files))
    
    dfp = pd.DataFrame(parsed_pdfs)
    logger.info(f"PDF processati: {len(dfp)}")
    logger.info(f"PDF con OCR: {(dfp['source']=='ocr').sum()}")
    logger.info(f"PDF con testo: {(dfp['source']=='text').sum()}")

    # Statistiche sul tipo di documento
    logger.info(f"Statistiche tipo documento:\n{dfp['doc_type'].value_counts().to_string()}")
    
    # 6) Costruisci tabella per atto (collapse allegati)
    # Raggruppiamo i PDF derivanti dallo stesso atto. Nello scraper i file sono nominati
    # solitamente come "titolo_idx.pdf". Rimuovendo il suffisso "_idx" raggruppiamo per atto originale.
    def get_atto_group(filename):
        stem = Path(filename).stem
        return re.sub(r'_\d+$', '', stem)
        
    dfp["atto_group"] = dfp["pdf_name"].apply(get_atto_group)
    
    df_atti = dfp.groupby("atto_group", dropna=False).agg({
        "doc_type": lambda x: next(iter([i for i in x if pd.notna(i) and i != "unknown"]), "unknown"),
        "category": lambda x: next(iter([i for i in x if pd.notna(i)]), None),
        "subcategory": lambda x: next(iter([i for i in x if pd.notna(i)]), None),
        "oggetto": lambda x: next(iter([i for i in x if pd.notna(i)]), None),
        "numero_atto": lambda x: next(iter([i for i in x if pd.notna(i)]), None),
        "data_atto": lambda x: next(iter([i for i in x if pd.notna(i)]), None),
        "importo_max": "max",
        "importo_sum": "sum",
        "cig": lambda x: ",".join(set(str(i) for i in x if pd.notna(i) and str(i).strip())),
        "cup": lambda x: ",".join(set(str(i) for i in x if pd.notna(i) and str(i).strip())),
        "beneficiario": lambda x: " | ".join(set(str(i) for i in x if pd.notna(i) and str(i).strip())),
        "accounting_relevant": "any",
        "missing_amount_expected": "any",
        "anomalie": lambda x: " | ".join(set(str(i) for i in x if pd.notna(i) and str(i).strip()))
    }).reset_index()

    # Rimuoviamo le stringhe vuote spurie generate dalle lambda
    for col in ["cig", "cup", "beneficiario", "anomalie"]:
        df_atti[col] = df_atti[col].replace("", None)

    out_csv_failed = base / "failed_extractions.csv"
    failed_df = dfp[dfp["source"].isin(["p7m_extraction_failed", "error", "unknown"]) | (dfp["text_chars"].fillna(0) < 50)]

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
        "accounting_relevant", "missing_amount_expected", "importo_lettere", "piva_beneficiario",
        "iban", "codice_appalti", "quadro_economico", "anomalie"
    ]
    dff = dfp[[c for c in feature_cols if c in dfp.columns]].copy()

    # 7) Salva CSV/Excel
    logger.info("Salvataggio CSV...")
    dfp.to_csv(out_csv_allegati, index=False, encoding="utf-8")
    dff.to_csv(out_csv_features, index=False, encoding="utf-8")
    if not args.no_corpus:
        text_dir.mkdir(parents=True, exist_ok=True)
        with open(out_corpus_jsonl, "w", encoding="utf-8") as f:
            for row in corpus_rows:
                text_path = Path(row["text_path"])
                text_path.write_text(row["text"], encoding="utf-8", errors="ignore")
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    
    df_atti.to_csv(out_csv_atti, index=False, encoding="utf-8")
    if not failed_df.empty:
        failed_df.to_csv(out_csv_failed, index=False, encoding="utf-8")
    
    logger.info("CSV salvati con successo!")
    logger.info("Salvataggio Excel con motore 'xlsxwriter'...")
    
    try:
        with pd.ExcelWriter(out_xlsx, engine="xlsxwriter") as xl:
            dfp.to_excel(xl, index=False, sheet_name="pdf_analisi")
            kpi_source.to_excel(xl, index=False, sheet_name="kpi_source")
            kpi_visto.to_excel(xl, index=False, sheet_name="kpi_visto_contabile")
            kpi_doctype.to_excel(xl, index=False, sheet_name="kpi_doctype")
            dff.to_excel(xl, index=False, sheet_name="features_ml")
            fornitori.head(50).to_excel(xl, index=False, sheet_name="fornitori_top50")
            # Aggiungiamo i due fogli mancanti e corretti
            df_atti.to_excel(xl, index=False, sheet_name="atti_estratti")
            df.to_excel(xl, index=False, sheet_name="metadati") # Usa df (non esploso) invece di dfa
            
            # Crea un foglio dedicato per revisionare comodamente le predizioni del modello ML
            ml_preds = dfp[dfp['classification_confidence'] == 'ml_predicted']
            if not ml_preds.empty:
                cols_review = [c for c in ["pdf_name", "doc_type", "category", "oggetto", "text_preview"] if c in dfp.columns]
                df_review = ml_preds[cols_review].copy()
                df_review.insert(3, 'categoria_corretta', None) # Colonna vuota per il feedback umano
                df_review.to_excel(xl, index=False, sheet_name="revisione_ml")
                
            # Salva gli atti con anomalie per il feedback loop (Active Learning)
            anomalies_df = dfp[dfp['anomalie'].notna()]
            if not anomalies_df.empty:
                df_anomalies_review = anomalies_df[['pdf_name', 'importo_max', 'importo_lettere', 'piva_beneficiario', 'iban', 'anomalie', 'text_preview']].copy()
                df_anomalies_review.insert(6, 'conferma_anomalia', None) # Scrivere 'NO' per segnalare un falso positivo
                df_anomalies_review.to_excel(xl, index=False, sheet_name="anomalie_da_addestrare")
        
        logger.info("Excel salvato con successo!")
    except Exception as e:
        logger.warning(f"Errore salvataggio Excel con xlsxwriter: {e}")
        logger.info("I dati CSV sono comunque disponibili!")

    logger.info(f"Salvati:\n- {out_csv_allegati}\n- {out_csv_atti}\n- {out_csv_features}\n- {out_corpus_jsonl if not args.no_corpus else '(corpus disattivato)'}\n- {out_xlsx} (se riuscito)")
    
    metrics.export_to_file(str((base / "metrics_analyze_albo.json").resolve()))

if __name__ == "__main__":
    main()
