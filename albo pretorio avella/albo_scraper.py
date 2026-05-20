#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry point principale dello scraper Albo Pretorio Avella.

La logica mantenuta vive in new_albo_scraper.py per evitare due scraper
divergenti nello stesso progetto.
"""

if __name__ == "__main__":
    from new_albo_scraper import main as _main
    _main()
    raise SystemExit

"""
Created on Wed Nov 12 14:44:13 2025

@author: 39329
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Albo Pretorio scraper (Comune di Avella - OpenWeb)
- Rispetta robots.txt e applica rate-limit.
- Scarica metadati delle pubblicazioni + allegati PDF.
- Segue la paginazione "classica" degli albi OpenWeb (link "Pagina successiva"/"Successivo").
- NON aggira login/captcha/protezioni. Usa solo contenuti pubblici.

Uso:
  python albo_scraper.py --start-url "https://.../albo_pretorio_full.php?CSRF=..." \
                         --out ./albo_download --max-pages 50 --delay 1.5

Note legali/prudenza:
- Non superare le policy del sito (robots.txt, condizioni d'uso).
- Evita raccolte massive di dati personali; se trovi PDF con dati sensibili, non ripubblicarli.
"""

import argparse
import csv
import os
import re
import sys
import time
import urllib.parse as up
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry
from urllib.robotparser import RobotFileParser


# -------------- Config di default --------------
DEFAULT_DELAY = 1.0          # secondi tra richieste
DEFAULT_MAX_PAGES = 20       # numero massimo di pagine da seguire
DEFAULT_TIMEOUT = 20         # timeout richieste http
USER_AGENT = "CivicResearchBot/1.0 (+contatto: pec o email tua) requests"


# -------------- Utility --------------
def slugify(text: str, maxlen: int = 120) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^\w\-.]+", "", text, flags=re.UNICODE)
    return text[:maxlen] or "file"

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def find_next_page(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """
    Cerca link di paginazione tipici:
    - 'Pagina successiva', 'Successivo', '»', '>' o rel=next
    - molti albi OpenWeb mettono i numeri pagina in fondo
    """
    # rel=next
    a = soup.find("a", rel=lambda v: v and "next" in v.lower())
    if a and a.get("href"):
        return up.urljoin(base_url, a["href"])

    # testi comuni
    candidates = soup.find_all("a", string=re.compile(r"(successiva|successivo|pagina successiva|avanti|>)", re.I))
    for c in candidates:
        href = c.get("href")
        if href:
            return up.urljoin(base_url, href)

    # pulsanti numerici con ">" o ">>"
    for a in soup.select("a"):
        txt = (a.get_text() or "").strip()
        if txt in (">", "»", ">>") and a.get("href"):
            return up.urljoin(base_url, a["href"])

    return None

def polite_sleep(delay: float):
    try:
        time.sleep(max(0.1, delay))
    except KeyboardInterrupt:
        raise

def load_robots_allow(base_root: str, user_agent: str = USER_AGENT) -> RobotFileParser:
    robots_url = up.urljoin(base_root, "/robots.txt")
    rp = RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        # se non raggiungibile, continuiamo ma restiamo prudenti
        pass
    return rp

def can_fetch(rp: RobotFileParser, url: str, user_agent: str = USER_AGENT) -> bool:
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True  # fallback prudente


# -------------- Data model --------------
@dataclass
class AlboItem:
    page_url: str
    titolo: str
    numero: Optional[str]
    data_pubblicazione: Optional[str]
    tipologia: Optional[str]
    ufficio: Optional[str]
    oggetto: Optional[str]
    dettaglio_url: Optional[str]
    allegati: List[str]


# -------------- Parser pagina elenco/dettaglio --------------
def parse_list_page(html: str, base_url: str) -> Tuple[List[AlboItem], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[AlboItem] = []

    # Struttura molto variabile: proviamo selettori robusti
    # Tipico: una tabella con righe contenenti titolo/oggetto e link "Dettagli" o direttamente ai PDF
    rows = soup.select("table tr") or soup.select("div.risultato, div.elenco, li")
    for r in rows:
        # troviamo un link di dettaglio
        a = r.find("a", href=True)
        if not a:
            continue

        href = up.urljoin(base_url, a["href"])
        text = " ".join((a.get_text() or "").split())

        # catturiamo qualche campo vicino
        row_text = " ".join((r.get_text(separator=" | ") or "").split())

        # euristiche per numero/data/tipologia
        m_num = re.search(r"\b(n\.|numero)\s*[:\s]*([0-9/]+)", row_text, re.I)
        m_data = re.search(r"\b(pubblicazione|affissione|dal|data)\s*[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", row_text, re.I)
        m_tip = re.search(r"\b(delibera|determinazione|ordinanza|avviso|bando)\b", row_text, re.I)

        item = AlboItem(
            page_url=base_url,
            titolo=text or "Senza titolo",
            numero=m_num.group(2) if m_num else None,
            data_pubblicazione=m_data.group(2) if m_data else None,
            tipologia=m_tip.group(1).capitalize() if m_tip else None,
            ufficio=None,
            oggetto=None,
            dettaglio_url=href,
            allegati=[]
        )
        items.append(item)

    next_url = find_next_page(soup, base_url)
    return items, next_url

def parse_detail_page(html: str, base_url: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    soup = BeautifulSoup(html, "html.parser")

    # oggetto/ufficio spesso sono in tabelle descrittive
    text = " ".join((soup.get_text(separator=" | ") or "").split())

    # oggetto
    ogg = None
    m_ogg = re.search(r"\b(oggetto|titolo)\b\s*[:|]\s*(.+?)(?:\s*\|\s*|$)", text, re.I)
    if m_ogg:
        ogg = m_ogg.group(2).strip()

    # ufficio
    uff = None
    m_uff = re.search(r"\b(ufficio|settore|area)\b\s*[:|]\s*(.+?)(?:\s*\|\s*|$)", text, re.I)
    if m_uff:
        uff = m_uff.group(2).strip()

    # allegati (pdf, doc, etc.)
    allegati = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(href.lower().endswith(ext) for ext in (".pdf", ".doc", ".docx", ".rtf", ".zip")):
            allegati.append(up.urljoin(base_url, href))

    # se non ci sono allegati ma il link è diretto a pdf, aggiungi base_url stesso (capita su alcuni albi)
    if not allegati and base_url.lower().endswith(".pdf"):
        allegati.append(base_url)

    return ogg, uff, list(dict.fromkeys(allegati))  # dedup


# -------------- Scraper --------------
class AlboScraper:
    def __init__(self, start_url: str, out_dir: Path, delay: float, max_pages: int, timeout: int):
        self.start_url = start_url
        self.out_dir = out_dir
        self.delay = delay
        self.max_pages = max_pages
        self.timeout = timeout

        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update({"User-Agent": USER_AGENT})

        # base root per robots.txt
        parsed = up.urlparse(self.start_url)
        self.base_root = f"{parsed.scheme}://{parsed.netloc}"
        self.rp = load_robots_allow(self.base_root)

        ensure_dir(self.out_dir)
        ensure_dir(self.out_dir / "pdf")

        # CSV metadati
        self.csv_path = self.out_dir / "albo_metadati.csv"
        if not self.csv_path.exists():
            with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(asdict(AlboItem("", "", "", "", "", "", "", "", [])).keys()))
                w.writeheader()

    def fetch(self, url: str) -> Optional[str]:
        if not can_fetch(self.rp, url):
            print(f"[robots] Vietato da robots.txt: {url}")
            return None
        polite_sleep(self.delay)
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        # alcune pagine hanno encoding windows-1252/latin-1
        r.encoding = r.apparent_encoding or r.encoding
        return r.text

    def download_file(self, url: str, dest: Path):
        if not can_fetch(self.rp, url):
            print(f"[robots] Vietato da robots.txt: {url}")
            return
        polite_sleep(self.delay)
        with self.session.get(url, stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

    def run(self):
        current_url = self.start_url
        visited_pages = 0

        while current_url and visited_pages < self.max_pages:
            print(f"[pagina] {visited_pages+1}: {current_url}")
            html = self.fetch(current_url)
            if not html:
                break

            items, next_url = parse_list_page(html, current_url)

            # per ciascun elemento, apri dettaglio e scarica allegati
            for it in items:
                try:
                    if it.dettaglio_url:
                        d_html = self.fetch(it.dettaglio_url)
                        if d_html:
                            ogg, uff, allegati = parse_detail_page(d_html, it.dettaglio_url)
                            it.oggetto = ogg or it.oggetto
                            it.ufficio = uff or it.ufficio
                            it.allegati = allegati

                    # salva metadati
                    with open(self.csv_path, "a", encoding="utf-8", newline="") as f:
                        w = csv.DictWriter(f, fieldnames=list(asdict(it).keys()))
                        w.writerow(asdict(it))

                    # scarica allegati
                    for idx, url in enumerate(it.allegati, 1):
                        stem = slugify(f"{it.tipologia or 'atto'}_{it.numero or ''}_{it.data_pubblicazione or ''}_{it.titolo}")[:100]
                        ext = os.path.splitext(up.urlparse(url).path)[1] or ".pdf"
                        dest = self.out_dir / "pdf" / f"{stem}_{idx}{ext}"
                        if not dest.exists():
                            print(f"  ↳ allegato: {url}")
                            self.download_file(url, dest)

                except KeyboardInterrupt:
                    print("\nInterrotto dall'utente.")
                    sys.exit(1)
                except Exception as e:
                    print(f"[warn] errore su item: {e}")

            visited_pages += 1
            current_url = next_url

        print(f"\nCompletato. Metadati: {self.csv_path}\nAllegati: {self.out_dir / 'pdf'}")


# -------------- CLI --------------
def main():
    ap = argparse.ArgumentParser(description="Scraper Albo Pretorio (OpenWeb)")
    ap.add_argument("--start-url", required=True, help="URL iniziale dell'albo (lista atti).")
    ap.add_argument("--out", default="./albo_download", help="Cartella di output.")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Numero massimo di pagine da seguire.")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay (secondi) tra richieste.")
    args = ap.parse_args()

    out_dir = Path(args.out)
    scraper = AlboScraper(
        start_url=args.start_url,
        out_dir=out_dir,
        delay=args.delay,
        max_pages=args.max_pages,
        timeout=DEFAULT_TIMEOUT,
    )
    try:
        scraper.run()
    except requests.HTTPError as e:
        print(f"[http] {e}")
        sys.exit(2)
    except Exception as e:
        print(f"[fatal] {e}")
        sys.exit(2)

if __name__ == "__main__":
    main()
