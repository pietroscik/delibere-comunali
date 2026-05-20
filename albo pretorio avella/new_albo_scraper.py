# -*- coding: utf-8 -*-
"""
Created on Wed Nov 12 15:20:11 2025

@author: 39329
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Albo Pretorio scraper (OpenWeb – Comune di Avella)
- Rispetta robots.txt e applica rate-limit.
- Scarica metadati + allegati (PDF/DOC/ZIP) con filtri e range pagine.
- Paginazione robusta: link "successivo" o calcolo page/start.
- Evita doppioni, supporta resume, logga su file.

Esempi:
  # prime 50 pagine
  python albo_scraper.py --start-url "https://servizi.comune.avella.av.it/openweb/albo/albo_pretorio_full.php?CSRF=XXXX" --out ./albo_download --max-pages 50 --delay 1.5

  # pagine 51–100 (senza CSRF)
  python albo_scraper.py --page-from 51 --page-to 100 --out ./albo_download --delay 1.5

  # solo delibere 2024, senza scaricare PDF
  python albo_scraper.py --page-from 1 --page-to 80 --only-types Delibera --date-from 2024-01-01 --date-to 2024-12-31 --no-download

Note legali:
- Non aggirare protezioni. Rispetta robots.txt, TOS e GDPR.
"""

import argparse
import ast
import csv
import json
import hashlib
import mimetypes
import os
import re
import sys
import time
import urllib.parse as up
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry
from urllib.robotparser import RobotFileParser

# -------------- Config di default --------------
DEFAULT_DELAY = 1.0
DEFAULT_MAX_PAGES = 20
DEFAULT_TIMEOUT = 20
DEFAULT_USER_AGENT = "CivicResearchBot/1.1 (+contatto: tua-pec-o-email)"

OPENWEB_BASE = "https://servizi.comune.avella.av.it/openweb/albo/albo_pretorio_full.php"

ATTACH_EXTS = (".pdf", ".doc", ".docx", ".rtf", ".zip")
ATTACH_MIME_EXT = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/zip": ".zip",
}

# -------------- Utility --------------
def slugify(text: str, maxlen: int = 120) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^\w\-.]+", "", text, flags=re.UNICODE)
    return text[:maxlen] or "file"

def compact_text(text: str) -> str:
    return " ".join((text or "").split())

def url_doc_name(url: str) -> str:
    """Restituisce il nome documento più informativo da path o query string."""
    pu = up.urlparse(url)
    qs = up.parse_qs(pu.query, keep_blank_values=True)
    for key in ("f", "file", "filename", "name"):
        if qs.get(key):
            return os.path.basename(qs[key][0])
    return os.path.basename(pu.path)

def looks_like_attachment(href: str, label: str = "") -> bool:
    name = url_doc_name(href).lower()
    text = (label or "").lower()
    if any(name.endswith(ext) for ext in ATTACH_EXTS):
        return True
    if "getdoc.php" in href.lower():
        return True
    return any(word in text for word in ("allegato", "documento", "pdf", "download", "vai"))

def infer_type(text: str) -> Optional[str]:
    t = (text or "").lower()
    rules = [
        ("Determinazione", ("determina", "determinazione")),
        ("Delibera", ("delibera", "deliberazione")),
        ("Ordinanza", ("ordinanza",)),
        ("Avviso", ("avviso",)),
        ("Bando", ("bando",)),
    ]
    for label, needles in rules:
        if any(n in t for n in needles):
            return label
    return None

def infer_number(text: str) -> Optional[str]:
    patterns = [
        r"\b(?:n\.|numero|copia|originale)[_\s-]*(\d{1,6})\b",
        r"_(\d{1,6})_(?:20\d{2})\b",
        r"\b(\d{1,6})/(20\d{2})\b",
    ]
    for rx in patterns:
        m = re.search(rx, text or "", re.I)
        if m:
            return m.group(1)
    return None

def infer_date(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{2}/\d{2}/\d{4}|20\d{2}-\d{2}-\d{2})\b", text or "")
    if m:
        return m.group(1)
    m = re.search(r"\b(20\d{2})\b", text or "")
    if m:
        return m.group(1)
    return None

def metadata_key(it: "AlboItem") -> str:
    if it.dettaglio_url:
        return it.dettaglio_url
    if it.allegati:
        return it.allegati[0]
    raw = "|".join([it.titolo or "", it.numero or "", it.data_pubblicazione or "", it.oggetto or ""])
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

def encode_query(query: dict) -> str:
    return up.urlencode(query, doseq=True, safe="[]")

def page_url(page: int, step: int = 15, csrf: Optional[str] = None) -> str:
    start = 1 + (max(1, page) - 1) * step
    q = {"tabella_albo[page]": [str(max(1, page))], "tabella_albo[start]": [str(start)]}
    if csrf:
        q = {"CSRF": [csrf], **q}
    return OPENWEB_BASE + "?" + encode_query(q)

def extract_csrf(html: str, final_url: str = "") -> Optional[str]:
    for source in (final_url, html or ""):
        m = re.search(r"CSRF=([A-Za-z0-9]+)", source)
        if m:
            return m.group(1)
    soup = BeautifulSoup(html or "", "html.parser")
    field = soup.find("input", attrs={"name": "CSRF"})
    if field and field.get("value"):
        return field["value"]
    return None

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def polite_sleep(delay: float):
    time.sleep(max(0.1, delay))

def parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

def within_dates(d: Optional[str], dfrom: Optional[date], dto: Optional[date]) -> bool:
    if not (dfrom or dto):
        return True
    dd = parse_date(d)
    if not dd:
        return False
    if dfrom and dd < dfrom:
        return False
    if dto and dd > dto:
        return False
    return True

def load_robots_allow(base_root: str) -> RobotFileParser:
    robots_url = up.urljoin(base_root, "/robots.txt")
    rp = RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        pass
    return rp

def can_fetch(rp: RobotFileParser, url: str, user_agent: str) -> bool:
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True

def guess_next_url(base_url: str, step_default: int = 15) -> Optional[str]:
    """Fallback per OpenWeb: incrementa page/start se non troviamo link 'successivo'."""
    pu = up.urlparse(base_url)
    qs = up.parse_qs(pu.query, keep_blank_values=True)
    try:
        page = int(qs.get('tabella_albo[page]', ['1'])[0])
        start = int(qs.get('tabella_albo[start]', ['1'])[0])
    except Exception:
        # se non presenti, inizializziamo per passare alla pagina 2
        page, start = 1, 1

    # heuristica del passo: OpenWeb spesso usa 15; se è presente 'start', stimiamo dal valore
    step = step_default
    if start > 1:
        # prova a dedurre dal pattern (start = 1 + (page-1)*step) => step = round((start-1)/(page-1))
        try:
            if page > 1:
                est = int(round((start - 1) / (page - 1)))
                if 5 <= est <= 50:
                    step = est
        except Exception:
            pass

    page += 1
    start = 1 + (page - 1) * step
    qs['tabella_albo[page]'] = [str(page)]
    qs['tabella_albo[start]'] = [str(start)]
    new_q = encode_query(qs)
    return up.urlunparse((pu.scheme, pu.netloc, pu.path, pu.params, new_q, pu.fragment))

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
    allegati: List[str] = field(default_factory=list)

# -------------- Parser pagina elenco/dettaglio --------------
TIPO_RX = re.compile(r"\b(delibera|determinazione|ordinanza|avviso|bando)\b", re.I)
NUM_RX = re.compile(r"\b(n\.|numero)\s*[:\s]*([0-9/]+)", re.I)
DATA_RX = re.compile(r"\b(pubblicazione|affissione|dal|data)\s*[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", re.I)

def parse_list_page(html: str, base_url: str) -> Tuple[List[AlboItem], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[AlboItem] = []

    rows = soup.select("table tr")
    if not rows:
        rows = soup.select("div.risultato, div.elenco, li")

    for r in rows:
        a = r.find("a", href=True)
        if not a:
            continue
        href = up.urljoin(base_url, a["href"])
        text = " ".join((a.get_text() or "").split())
        row_text = " ".join((r.get_text(separator=" | ") or "").split())

        m_num = NUM_RX.search(row_text)
        m_data = DATA_RX.search(row_text)
        m_tip = TIPO_RX.search(row_text)

        item = AlboItem(
            page_url=base_url,
            titolo=text or "Senza titolo",
            numero=m_num.group(2) if m_num else None,
            data_pubblicazione=m_data.group(2) if m_data else None,
            tipologia=(m_tip.group(1).capitalize() if m_tip else None),
            ufficio=None,
            oggetto=None,
            dettaglio_url=href,
        )
        items.append(item)

    # Link "successivo" o rel=next
    a_next = soup.find("a", rel=lambda v: v and "next" in v.lower())
    if a_next and a_next.get("href"):
        return items, up.urljoin(base_url, a_next["href"])

    for c in soup.find_all("a", string=re.compile(r"(successiva|successivo|pagina successiva|avanti|>)", re.I)):
        if c.get("href"):
            return items, up.urljoin(base_url, c["href"])

    for a in soup.select("a"):
        txt = (a.get_text() or "").strip()
        if txt in (">", "»", ">>") and a.get("href"):
            return items, up.urljoin(base_url, a["href"])

    # fallback
    return items, guess_next_url(base_url)

def parse_detail_page(html: str, base_url: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    text = compact_text(soup.get_text(separator=" | "))

    ogg = None
    m_ogg = re.search(
        r"\b(?:oggetto|titolo)\b\s*[:|]\s*(.+?)(?=\s*\|\s*(?:ufficio|settore|area|allegati?|pubblicazione|numero)\b|\s*$)",
        text,
        re.I,
    )
    if m_ogg:
        ogg = m_ogg.group(1).strip(" :-|")

    uff = None
    m_uff = re.search(
        r"\b(?:ufficio|settore|area)\b\s*[:|]\s*(.+?)(?=\s*\|\s*(?:oggetto|titolo|allegati?|pubblicazione|numero)\b|\s*$)",
        text,
        re.I,
    )
    if m_uff:
        uff = m_uff.group(1).strip(" :-|")

    allegati = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = compact_text(a.get_text(" "))
        if looks_like_attachment(href, label):
            allegati.append(up.urljoin(base_url, href))

    if not allegati and base_url.lower().endswith(".pdf"):
        allegati.append(base_url)

    # dedup
    seen = {}
    out = []
    for u in allegati:
        if u not in seen:
            seen[u] = 1
            out.append(u)
    return ogg, uff, out

# -------------- Scraper --------------
class AlboScraper:
    def __init__(self, args):
        self.args = args
        self.out_dir = Path(args.out)
        ensure_dir(self.out_dir)
        ensure_dir(self.out_dir / "pdf")
        if args.save_html:
            ensure_dir(self.out_dir / "html")
        # log file
        self.log_path = self.out_dir / "albo_scraper.log"
        # CSV metadati
        self.csv_path = self.out_dir / "albo_metadati.csv"
        if not self.csv_path.exists():
            with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(asdict(AlboItem("", "", "", "", "", "", "", "", [])).keys()))
                w.writeheader()
        self.seen_metadata = self._load_seen_metadata()
        # registro URL scaricati (opzionale)
        self.downloaded_json = self.out_dir / "downloads.json"
        if self.downloaded_json.exists():
            try:
                self.downloaded = set(json.loads(self.downloaded_json.read_text(encoding="utf-8")))
            except Exception:
                self.downloaded = set()
        else:
            self.downloaded = set()

        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update({"User-Agent": args.user_agent or DEFAULT_USER_AGENT})

        parsed = up.urlparse(args.start_url) if args.start_url else up.urlparse(OPENWEB_BASE)
        self.base_root = f"{parsed.scheme}://{parsed.netloc}"
        self.rp = load_robots_allow(self.base_root)

        # Se page-from è impostato, costruisci URL iniziale
        if args.page_from is not None:
            page = max(1, args.page_from)
            step = args.page_step or 15
            csrf = self.bootstrap_csrf()
            self.current_url = page_url(page, step=step, csrf=csrf)
            # forza max_pages = page_to - page + 1 se specificato
            if args.page_to is not None and args.page_to >= page:
                self.max_pages = args.page_to - page + 1
            else:
                self.max_pages = args.max_pages
        else:
            self.current_url = args.start_url
            self.max_pages = args.max_pages

        self.delay = args.delay
        self.timeout = args.timeout

        # Prepara filtri
        self.only_types = set([t.strip().lower() for t in (args.only_types or "").split(",") if t.strip()]) or None
        self.exclude_types = set([t.strip().lower() for t in (args.exclude_types or "").split(",") if t.strip()]) or None
        self.title_rx = re.compile(args.title_regex, re.I) if args.title_regex else None
        self.dfrom = parse_date(args.date_from) if args.date_from else None
        self.dto = parse_date(args.date_to) if args.date_to else None

    def _load_seen_metadata(self) -> set:
        seen = set()
        if not self.csv_path.exists():
            return seen
        try:
            with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    key = self._metadata_key_from_row(row)
                    if key:
                        seen.add(key)
                    dettaglio = (row.get("dettaglio_url") or "").strip()
                    if dettaglio:
                        seen.add(dettaglio)
        except Exception:
            pass
        return seen

    @staticmethod
    def _parse_allegati_field(raw: Optional[str]) -> List[str]:
        if not raw:
            return []
        txt = str(raw).strip()
        if not txt:
            return []
        for parser in (ast.literal_eval, json.loads):
            try:
                val = parser(txt)
                if isinstance(val, list):
                    return [str(x).strip() for x in val if str(x).strip()]
            except Exception:
                pass
        if ";" in txt:
            return [x.strip() for x in txt.split(";") if x.strip()]
        if "|" in txt:
            return [x.strip() for x in txt.split("|") if x.strip()]
        return [txt]

    def _metadata_key_from_row(self, row: dict) -> str:
        dettaglio_url = (row.get("dettaglio_url") or "").strip()
        if dettaglio_url:
            return dettaglio_url
        allegati = self._parse_allegati_field(row.get("allegati"))
        if allegati:
            return allegati[0]
        raw = "|".join([
            row.get("titolo") or "",
            row.get("numero") or "",
            row.get("data_pubblicazione") or "",
            row.get("oggetto") or "",
        ])
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def bootstrap_csrf(self) -> Optional[str]:
        """Apre la pagina base per ottenere eventuale token CSRF richiesto da OpenWeb."""
        try:
            if not can_fetch(self.rp, OPENWEB_BASE, self.args.user_agent or DEFAULT_USER_AGENT):
                return None
            r = self.session.get(OPENWEB_BASE, timeout=self.args.timeout)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or r.encoding
            csrf = extract_csrf(r.text, r.url)
            if csrf:
                self.log("[sessione] CSRF recuperato dalla pagina base")
            return csrf
        except Exception as e:
            self.log(f"[sessione] impossibile recuperare CSRF dalla pagina base: {e}")
            return None

    def log(self, msg: str):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def fetch(self, url: str) -> Optional[str]:
        if not can_fetch(self.rp, url, self.args.user_agent or DEFAULT_USER_AGENT):
            self.log(f"[robots] Vietato da robots.txt: {url}")
            return None
        polite_sleep(self.delay)
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding
        return r.text

    def download_file(self, url: str, dest: Path):
        if url in self.downloaded:
            return
        if not can_fetch(self.rp, url, self.args.user_agent or DEFAULT_USER_AGENT):
            self.log(f"[robots] Vietato da robots.txt: {url}")
            return
        polite_sleep(self.delay)
        with self.session.get(url, stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            real_ext = self.extension_for_response(url, r)
            if real_ext and dest.suffix.lower() != real_ext:
                dest = dest.with_suffix(real_ext)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        self.downloaded.add(url)
        try:
            self.downloaded_json.write_text(json.dumps(sorted(self.downloaded)), encoding="utf-8")
        except Exception:
            pass

    def extension_for_response(self, url: str, response: requests.Response) -> str:
        ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype in ATTACH_MIME_EXT:
            return ATTACH_MIME_EXT[ctype]
        guessed = mimetypes.guess_extension(ctype) if ctype else None
        if guessed:
            return guessed
        name = url_doc_name(url)
        ext = os.path.splitext(name)[1].lower()
        return ext if ext else ".bin"

    def enrich_item(self, it: AlboItem) -> None:
        source = " ".join([it.titolo or "", it.oggetto or "", " ".join(url_doc_name(u) for u in it.allegati)])
        if not it.tipologia:
            it.tipologia = infer_type(source)
        if not it.numero:
            it.numero = infer_number(source)
        if not it.data_pubblicazione:
            it.data_pubblicazione = infer_date(source)
        if (not it.titolo or it.titolo.lower() == "vai") and it.oggetto:
            it.titolo = it.oggetto[:180]

    def write_metadata_once(self, it: AlboItem) -> bool:
        key = metadata_key(it)
        if key in self.seen_metadata:
            return False
        with open(self.csv_path, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(it).keys()))
            w.writerow(asdict(it))
        self.seen_metadata.add(key)
        if it.dettaglio_url:
            self.seen_metadata.add(it.dettaglio_url)
        for attachment in it.allegati:
            if attachment:
                self.seen_metadata.add(attachment)
        return True

    def item_passes_filters(self, it: AlboItem) -> bool:
        # tipo
        if self.only_types and (it.tipologia or "").lower() not in self.only_types:
            return False
        if self.exclude_types and (it.tipologia or "").lower() in self.exclude_types:
            return False
        # date
        if not within_dates(it.data_pubblicazione, self.dfrom, self.dto):
            return False
        # titolo/oggetto regex
        txt = (it.titolo or "") + " " + (it.oggetto or "")
        if self.title_rx and not self.title_rx.search(txt):
            return False
        return True

    def run(self):
        current_url = self.current_url
        visited_pages = 0
        visited_urls = set()

        while current_url and visited_pages < self.max_pages:
            if current_url in visited_urls:
                self.log(f"[stop] URL pagina gia' visitato: {current_url}")
                break
            visited_urls.add(current_url)
            self.log(f"[pagina] {visited_pages+1}: {current_url}")
            try:
                html = self.fetch(current_url)
            except requests.HTTPError as e:
                self.log(f"[http] {e}")
                break
            except Exception as e:
                self.log(f"[fatal] {e}")
                break
            if not html:
                break

            items, next_url = parse_list_page(html, current_url)
            if not items:
                self.log("[stop] nessun atto trovato nella pagina corrente")
                break

            for it in items:
                try:
                    # Salta l'atto se è già stato scaricato e indicizzato in precedenza
                    if it.dettaglio_url and it.dettaglio_url in self.seen_metadata:
                        self.log(f"  [skip] Già in archivio: {it.dettaglio_url}")
                        continue

                    # dettaglio
                    if it.dettaglio_url:
                        d_html = self.fetch(it.dettaglio_url)
                        if d_html:
                            ogg, uff, allegati = parse_detail_page(d_html, it.dettaglio_url)
                            it.oggetto = ogg or it.oggetto
                            it.ufficio = uff or it.ufficio
                            it.allegati = allegati
                            if self.args.save_html:
                                name = slugify(it.titolo or f"item_{it.numero or ''}") + ".html"
                                (self.out_dir / "html" / name).write_text(d_html, encoding="utf-8", errors="ignore")

                    self.enrich_item(it)

                    # filtri a valle (dopo aver popolato oggetto/ufficio)
                    if not self.item_passes_filters(it):
                        continue

                    # salva metadati
                    self.write_metadata_once(it)

                    # scarica allegati
                    if not self.args.no_download:
                        to_dl = it.allegati
                        if self.args.max_attachments_per_item is not None:
                            to_dl = to_dl[: max(0, int(self.args.max_attachments_per_item))]
                        for idx, url in enumerate(to_dl, 1):
                            doc_name = os.path.splitext(url_doc_name(url))[0]
                            stem = slugify(f"{it.tipologia or 'atto'}_{it.numero or ''}_{it.data_pubblicazione or ''}_{doc_name or it.titolo}")[:100]
                            ext = os.path.splitext(url_doc_name(url))[1] or ".pdf"
                            dest = self.out_dir / "pdf" / f"{stem}_{idx}{ext}"
                            if not dest.exists():
                                self.log(f"  ↳ allegato: {url}")
                                self.download_file(url, dest)

                except KeyboardInterrupt:
                    self.log("Interrotto dall'utente.")
                    sys.exit(1)
                except Exception as e:
                    self.log(f"[warn] errore su item: {e}")

            visited_pages += 1
            current_url = next_url

        self.log(f"Completato. CSV: {self.csv_path} | PDF: {self.out_dir / 'pdf'}")

# -------------- CLI --------------
def build_parser():
    ap = argparse.ArgumentParser(description="Scraper Albo Pretorio (OpenWeb)")
    ap.add_argument("--start-url", help="URL iniziale (lista atti). Ignorato se usi --page-from.")
    ap.add_argument("--out", default="./albo_download", help="Cartella di output.")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="Numero max pagine da seguire.")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay (s) tra richieste.")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Timeout richieste (s).")
    ap.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent HTTP (metti contatto/PEC).")

    # Range di pagine
    ap.add_argument("--page-from", type=int, default=None, help="Pagina iniziale (costruisce URL base OpenWeb).")
    ap.add_argument("--page-to", type=int, default=None, help="Pagina finale (inclusa).")
    ap.add_argument("--page-step", type=int, default=15, help="Passo 'start' per pagina (default 15).")

    # Filtri
    ap.add_argument("--only-types", help="Esempio: 'Delibera,Determinazione'")
    ap.add_argument("--exclude-types", help="Esempio: 'Avviso,Bando'")
    ap.add_argument("--date-from", help="YYYY-MM-DD o DD/MM/YYYY")
    ap.add_argument("--date-to", help="YYYY-MM-DD o DD/MM/YYYY")
    ap.add_argument("--title-regex", help="Regex su titolo/oggetto (es. 'bilancio|rendiconto')")

    # Download comportamenti
    ap.add_argument("--no-download", action="store_true", help="Non scaricare allegati (solo CSV).")
    ap.add_argument("--max-attachments-per-item", type=int, default=None, help="Limita n. allegati per atto.")
    ap.add_argument("--save-html", action="store_true", help="Salva HTML del dettaglio per debug.")
    return ap

def main():
    args = build_parser().parse_args()

    # Precondizioni minime
    if args.page_from is None and not args.start_url:
        print("Errore: specifica --start-url oppure --page-from/--page-to.", file=sys.stderr)
        sys.exit(2)

    scraper = AlboScraper(args)
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
