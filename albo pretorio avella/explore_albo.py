#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Report esplorativo e piano di ottimizzazione ricorsiva per il corpus Albo.

Input attesi in --base:
- documenti_features.csv
- allegati_parsed.csv
- atti_parsed.csv
- albo_metadati.csv
- documenti_corpus.jsonl
"""

import argparse
import json
from pathlib import Path

import pandas as pd


def pct(value, total):
    if not total:
        return 0.0
    return round((float(value) / float(total)) * 100.0, 2)


def value_counts_frame(series, name, top=30):
    vc = series.fillna("<vuoto>").astype(str).value_counts().head(top)
    return vc.rename_axis(name).reset_index(name="count")


def read_jsonl_sample(path, limit=5):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            rows.append(json.loads(line))
    return rows


def quality_issues(features, allegati, metadati):
    total = len(features)
    issues = []

    no_category = int(features["category"].isna().sum()) if "category" in features else 0
    ambiguous = int((features.get("classification_confidence") == "ambiguous").sum()) if "classification_confidence" in features else 0
    short_text = int((features.get("text_words", pd.Series(dtype=int)).fillna(0) < 120).sum()) if "text_words" in features else 0
    unknown_type = int((features.get("doc_type", pd.Series(dtype=str)).fillna("unknown") == "unknown").sum()) if "doc_type" in features else 0
    no_amount = int(features["importo_max"].isna().sum()) if "importo_max" in features else 0
    if {"missing_amount_expected", "importo_max"}.issubset(features.columns):
        missing_expected_amount = int(features["missing_amount_expected"].fillna(False).astype(bool).sum())
    else:
        missing_expected_amount = no_amount
    duplicate_text = int(features.duplicated("text_sha256").sum()) if "text_sha256" in features else 0

    meta_total = len(metadati)
    meta_no_type = int(metadati["tipologia"].isna().sum()) if "tipologia" in metadati else 0
    meta_duplicate_detail = int(metadati.duplicated("dettaglio_url").sum()) if "dettaglio_url" in metadati else 0

    checks = [
        ("documenti_senza_categoria", no_category, total, "Ampliare dizionario categorie o passare a classificazione supervisionata."),
        ("classificazioni_ambigue", ambiguous, total, "Revisionare manualmente e usare come validation set."),
        ("testi_troppo_corti", short_text, total, "Controllare OCR, PDF vuoti o allegati non deliberativi."),
        ("tipo_documento_unknown", unknown_type, total, "Migliorare inferenza tipo da filename/testo."),
        ("documenti_senza_importi", no_amount, total, "Dato descrittivo: molti atti non devono contenere importi."),
        ("atti_contabili_senza_importi", missing_expected_amount, total, "Priorita' reale: migliorare regex importi/OCR sui soli atti contabili."),
        ("testi_duplicati", duplicate_text, total, "Deduplicare corpus prima di training/embedding."),
        ("metadati_senza_tipologia", meta_no_type, meta_total, "Rigenerare metadati puliti o ricavare tipologia dagli allegati."),
        ("metadati_dettaglio_duplicato", meta_duplicate_detail, meta_total, "Ripulire CSV storico e usare solo righe deduplicate."),
    ]

    for name, count, denom, recommendation in checks:
        issues.append({
            "issue": name,
            "count": count,
            "total": denom,
            "percent": pct(count, denom),
            "priority": priority(count, denom),
            "recommendation": recommendation,
        })
    return pd.DataFrame(issues).sort_values(["priority", "percent"], ascending=[True, False])


def priority(count, total):
    ratio = (count / total) if total else 0
    if count == 0:
        return 4
    if ratio >= 0.25:
        return 1
    if ratio >= 0.10:
        return 2
    return 3


def sensitivity_tables(features):
    tables = {}
    if "category" in features:
        tables["category_distribution"] = value_counts_frame(features["category"], "category")
    if "doc_type" in features:
        tables["doc_type_distribution"] = value_counts_frame(features["doc_type"], "doc_type")
    if "source" in features:
        tables["source_distribution"] = value_counts_frame(features["source"], "source")
    if "classification_confidence" in features:
        tables["confidence_distribution"] = value_counts_frame(features["classification_confidence"], "classification_confidence")

    if {"category", "text_words", "importo_max", "importi_count"}.issubset(features.columns):
        tables["category_numeric_profile"] = (
            features.groupby("category", dropna=False)
            .agg(
                docs=("pdf_name", "count"),
                text_words_mean=("text_words", "mean"),
                text_words_median=("text_words", "median"),
                importo_max_count=("importo_max", "count"),
                importo_max_sum=("importo_max", "sum"),
                importi_count_mean=("importi_count", "mean"),
                accounting_relevant_count=("accounting_relevant", "sum") if "accounting_relevant" in features else ("pdf_name", "count"),
                missing_amount_expected_count=("missing_amount_expected", "sum") if "missing_amount_expected" in features else ("pdf_name", "count"),
            )
            .reset_index()
            .sort_values("docs", ascending=False)
        )

    if {"doc_type", "category"}.issubset(features.columns):
        tables["doctype_category_matrix"] = pd.crosstab(
            features["doc_type"].fillna("<vuoto>"),
            features["category"].fillna("<vuoto>"),
        ).reset_index()

    return tables


def outliers(features):
    rows = {}
    if "text_words" in features:
        rows["short_text_documents"] = features.sort_values("text_words", ascending=True).head(50)
        rows["long_text_documents"] = features.sort_values("text_words", ascending=False).head(50)
    if "importo_max" in features:
        rows["top_importi"] = features.dropna(subset=["importo_max"]).sort_values("importo_max", ascending=False).head(50)
    if "classification_confidence" in features:
        rows["ambiguous_documents"] = features[features["classification_confidence"] == "ambiguous"].head(200)
    if "category" in features:
        rows["uncategorized_documents"] = features[features["category"].isna()].head(200)
    return rows


def write_markdown(path, base, features, allegati, metadati, issues, corpus_sample):
    lines = []
    lines.append("# Report Albo Pretorio Avella")
    lines.append("")
    lines.append("## Sintesi")
    lines.append("")
    lines.append(f"- PDF/documenti analizzati: {len(features)}")
    lines.append(f"- Allegati parsed: {len(allegati)}")
    lines.append(f"- Righe metadati: {len(metadati)}")
    if "text_words" in features:
        lines.append(f"- Parole medie per documento: {round(features['text_words'].fillna(0).mean(), 1)}")
        lines.append(f"- Parole mediane per documento: {round(features['text_words'].fillna(0).median(), 1)}")
    if "category" in features:
        lines.append(f"- Documenti senza categoria: {int(features['category'].isna().sum())} ({pct(features['category'].isna().sum(), len(features))}%)")
    if "classification_confidence" in features:
        ambiguous = int((features["classification_confidence"] == "ambiguous").sum())
        lines.append(f"- Classificazioni ambigue: {ambiguous} ({pct(ambiguous, len(features))}%)")
    lines.append("")

    lines.append("## Priorita' Di Ottimizzazione")
    lines.append("")
    for _, row in issues.iterrows():
        if row["count"] == 0:
            continue
        lines.append(
            f"- P{int(row['priority'])} `{row['issue']}`: {int(row['count'])}/{int(row['total'])} "
            f"({row['percent']}%). {row['recommendation']}"
        )
    lines.append("")

    lines.append("## Ciclo Ricorsivo Consigliato")
    lines.append("")
    lines.append("1. Misura: rigenera questo report dopo ogni scraping/analisi.")
    lines.append("2. Correggi: affronta prima le criticita' P1 e P2.")
    lines.append("3. Valida: controlla manualmente un campione di documenti ambigui/non categorizzati.")
    lines.append("4. Addestra: usa `documenti_corpus.jsonl` solo dopo deduplica e controllo OCR.")
    lines.append("5. Ripeti: confronta percentuali e distribuzioni tra iterazioni.")
    lines.append("")

    lines.append("## Output Generati")
    lines.append("")
    lines.append(f"- `{base / 'report' / 'quality_issues.csv'}`")
    lines.append(f"- `{base / 'report' / 'category_distribution.csv'}`")
    lines.append(f"- `{base / 'report' / 'category_numeric_profile.csv'}`")
    lines.append(f"- `{base / 'report' / 'albo_exploration.xlsx'}`")
    lines.append("")

    if corpus_sample:
        lines.append("## Campione Corpus")
        lines.append("")
        for row in corpus_sample[:3]:
            text = (row.get("text_preview") or row.get("text") or "")[:240].replace("\n", " ")
            lines.append(f"- `{row.get('pdf_name')}` | {row.get('doc_type')} | {row.get('category')}: {text}...")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Genera statistiche, anomalie e piano di ottimizzazione del corpus albo.")
    ap.add_argument("--base", default="./albo_download", help="Cartella con gli output di analyze_albo.py")
    args = ap.parse_args()

    base = Path(args.base)
    report_dir = base / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    features = pd.read_csv(base / "documenti_features.csv")
    allegati = pd.read_csv(base / "allegati_parsed.csv")
    metadati = pd.read_csv(base / "albo_metadati.csv")
    corpus_sample = read_jsonl_sample(base / "documenti_corpus.jsonl", limit=5)

    issues = quality_issues(features, allegati, metadati)
    issues.to_csv(report_dir / "quality_issues.csv", index=False, encoding="utf-8")

    tables = sensitivity_tables(features)
    for name, table in tables.items():
        table.to_csv(report_dir / f"{name}.csv", index=False, encoding="utf-8")

    outlier_tables = outliers(features)
    for name, table in outlier_tables.items():
        table.to_csv(report_dir / f"{name}.csv", index=False, encoding="utf-8")

    xlsx_path = report_dir / "albo_exploration.xlsx"
    try:
        with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as xl:
            issues.to_excel(xl, index=False, sheet_name="quality_issues")
            for name, table in {**tables, **outlier_tables}.items():
                table.to_excel(xl, index=False, sheet_name=name[:31])
    except ModuleNotFoundError:
        xlsx_path = None
        print("[WARN] xlsxwriter non installato: report Excel saltato, CSV e Markdown salvati.")

    write_markdown(report_dir / "report.md", base, features, allegati, metadati, issues, corpus_sample)

    print(f"[OK] Report salvato in: {report_dir}")
    print(f"- {report_dir / 'report.md'}")
    if xlsx_path:
        print(f"- {xlsx_path}")
    print(f"- {report_dir / 'quality_issues.csv'}")


if __name__ == "__main__":
    main()
