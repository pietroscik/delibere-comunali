from typing import Dict, Optional, List
from fuzzywuzzy import fuzz
from new_albo_scraper import infer_tipologia_from_filename, infer_tipologia_from_oggetto, infer_tipologia_from_url

def calculate_tipologia_confidence(
    tipologia: str,
    filename: str,
    oggetto: str,
    url: str,
    doc_type_from_ml: Optional[str] = None
) -> float:
    """Calcola probabilità che la tipologia sia corretta (0.0 - 1.0)."""
    score = 0.0
    weights = {"filename": 0.4, "oggetto": 0.3, "url": 0.2, "ml": 0.3}

    filename_tipologia = infer_tipologia_from_filename(filename)
    if filename_tipologia and fuzz.ratio(tipologia.lower(), filename_tipologia.lower()) > 80:
        score += weights["filename"]

    oggetto_tipologia = infer_tipologia_from_oggetto(oggetto)
    if oggetto_tipologia and fuzz.ratio(tipologia.lower(), oggetto_tipologia.lower()) > 80:
        score += weights["oggetto"]

    url_tipologia = infer_tipologia_from_url(url)
    if url_tipologia and fuzz.ratio(tipologia.lower(), url_tipologia.lower()) > 80:
        score += weights["url"]

    if doc_type_from_ml and fuzz.ratio(tipologia.lower(), doc_type_from_ml.lower()) > 80:
        score += weights["ml"]

    RARE_TIPOLOGIE = ["Altro", "VistoContabile", "AttestazionePubblicazione"]
    if tipologia in RARE_TIPOLOGIE:
        score *= 0.8

    return min(max(score, 0.0), 1.0)

def calculate_importi_confidence(importi: List[float], doc_type: str, category: str, testo_length: int) -> float:
    """Calcola probabilità che gli importi estratti siano corretti."""
    if doc_type not in ["Determinazione", "Delibera", "VistoContabile", "Bando"]:
        return 1.0

    if not importi:
        return 0.0

    reasonable_imports = [i for i in importi if 100 <= i <= 10_000_000]
    if not reasonable_imports:
        return 0.3

    if testo_length < 500 and len(importi) > 3:
        return 0.5

    return 1.0

def calculate_overall_confidence(tipologia_conf: float, importi_conf: float, classification_conf: str) -> float:
    """Calcola confidence complessivo per un documento."""
    conf_map = {
        "high": 1.0,
        "high_ml": 0.9,
        "ml_predicted": 0.7,
        "ambiguous": 0.3,
        "<vuoto>": 0.1,
    }
    classification_score = conf_map.get(classification_conf, 0.1)
    weights = {"tipologia": 0.4, "importi": 0.3, "classification": 0.3}
    return (tipologia_conf * weights["tipologia"] + importi_conf * weights["importi"] + classification_score * weights["classification"])