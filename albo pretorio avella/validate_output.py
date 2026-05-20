#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path

import pandas as pd


def pct(part, total):
    if not total:
        return 0.0
    return round((float(part) / float(total)) * 100.0, 2)


def validate_file(path: Path, required_cols):
    if not path.exists():
        return None, [f"file mancante: {path}"]
    try:
        df = pd.read_csv(path, encoding="utf-8")
    except Exception as exc:
        return None, [f"lettura fallita ({path}): {exc}"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return df, [f"colonne mancanti in {path.name}: {', '.join(missing)}"]
    return df, []


def main():
    ap = argparse.ArgumentParser(description="Valida gli output prodotti da analyze_albo.py")
    ap.add_argument("--base", default="./albo_download", help="Cartella output della pipeline")
    ap.add_argument(
        "--max-unknown-doc-type-pct",
        type=float,
        default=35.0,
        help="Soglia percentuale massima di doc_type=unknown (warning se superata).",
    )
    ap.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Se impostato, i warning fanno uscire con codice 1.",
    )
    args = ap.parse_args()

    base = Path(args.base)
    issues = []
    warnings = []

    df_features, errs = validate_file(
        base / "documenti_features.csv",
        [
            "pdf_name",
            "doc_type",
            "source",
            "text_sha256",
            "text_words",
            "category",
            "classification_confidence",
        ],
    )
    issues.extend(errs)

    df_allegati, errs = validate_file(
        base / "allegati_parsed.csv",
        ["pdf_name", "pdf_path", "doc_type", "source", "text_path"],
    )
    issues.extend(errs)

    if issues:
        for err in issues:
            print(f"[ERROR] {err}")
        raise SystemExit(2)

    total_docs = len(df_features)
    total_allegati = len(df_allegati)
    print(f"[INFO] documenti_features.csv: {total_docs} righe")
    print(f"[INFO] allegati_parsed.csv: {total_allegati} righe")

    duplicates_name = int(df_features.duplicated("pdf_name").sum())
    if duplicates_name:
        issues.append(f"duplicati pdf_name in documenti_features.csv: {duplicates_name}")

    duplicates_text = int(df_features.duplicated("text_sha256").sum())
    if duplicates_text:
        warnings.append(f"testi duplicati (text_sha256): {duplicates_text}")

    unknown_count = int((df_features["doc_type"] == "unknown").sum())
    unknown_pct = pct(unknown_count, total_docs)
    print(f"[INFO] doc_type unknown: {unknown_count}/{total_docs} ({unknown_pct}%)")
    if unknown_pct > args.max_unknown_doc_type_pct:
        warnings.append(
            f"doc_type=unknown oltre soglia: {unknown_pct}% > {args.max_unknown_doc_type_pct}%"
        )

    missing_text = int(df_allegati["text_path"].isna().sum())
    if missing_text:
        warnings.append(f"text_path mancanti in allegati_parsed.csv: {missing_text}")

    missing_category = int(df_features["category"].isna().sum())
    print(f"[INFO] category mancanti: {missing_category}/{total_docs} ({pct(missing_category, total_docs)}%)")

    ocr_count = int((df_features["source"] == "ocr").sum())
    print(f"[INFO] documenti OCR: {ocr_count}/{total_docs} ({pct(ocr_count, total_docs)}%)")

    if issues:
        for err in issues:
            print(f"[ERROR] {err}")
        raise SystemExit(2)

    if warnings:
        for warn in warnings:
            print(f"[WARN] {warn}")
        if args.fail_on_warning:
            raise SystemExit(1)
        print("[OK] Validazione completata con warning non bloccanti.")
        raise SystemExit(0)

    print("[OK] Validazione completata: nessun errore bloccante.")


if __name__ == "__main__":
    main()
