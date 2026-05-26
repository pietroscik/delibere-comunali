#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Orchestrates the analysis/training/validation pipeline.

Default flow:
1) analyze_albo.py
2) optional ML training (albo_download/randomForest.py)
3) optional second analyze_albo.py pass (to apply trained model)
4) optional clean_texts.py (opt-in)
5) validate_output.py
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List


SCRIPT_DIR = Path(__file__).resolve().parent


def run_step(command: List[str], label: str, cwd: Path) -> None:
    printable = " ".join(command)
    print(f"\n{'=' * 72}")
    print(f"STEP: {label}")
    print(f"CMD : {printable}")
    print(f"{'=' * 72}")
    result = subprocess.run(command, cwd=str(cwd), check=False)
    if result.returncode != 0:
        print(f"\nERROR: step failed ({label}) with exit code {result.returncode}.")
        raise SystemExit(result.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run complete Albo analysis pipeline.")
    parser.add_argument(
        "--base",
        default="./albo_download",
        help="Base output directory used by analyze/validate scripts.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run child scripts.",
    )
    parser.add_argument(
        "--skip-ml",
        action="store_true",
        help="Skip ML training and second analysis pass.",
    )
    parser.add_argument(
        "--strict-validation",
        action="store_true",
        help="Fail pipeline if validation emits warnings.",
    )
    parser.add_argument(
        "--clean-texts",
        action="store_true",
        help="Include clean_texts.py step before validation.",
    )
    parser.add_argument(
        "--skip-clean-texts",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Pass --use-llm to analyze_albo.py.",
    )
    parser.add_argument(
        "--no-corpus",
        action="store_true",
        help="Pass --no-corpus to analyze_albo.py.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    base = Path(args.base).expanduser()
    if not base.is_absolute():
        base = (SCRIPT_DIR / base).resolve()
    run_clean_texts = bool(args.clean_texts and not args.skip_clean_texts)

    analyze_cmd = [args.python, "analyze_albo.py", "--base", str(base)]
    if args.use_llm:
        analyze_cmd.append("--use-llm")
    if args.no_corpus:
        analyze_cmd.append("--no-corpus")

    run_step(analyze_cmd, "Analyze documents (pass 1)", SCRIPT_DIR)

    if not args.skip_ml:
        ml_candidates = [base / "randomForest.py", SCRIPT_DIR / "albo_download" / "randomForest.py"]
        ml_script = next((candidate for candidate in ml_candidates if candidate.exists()), None)
        if ml_script is not None:
            run_step([args.python, str(ml_script)], "Train ML model", SCRIPT_DIR)
            run_step(analyze_cmd, "Analyze documents (pass 2 with ML)", SCRIPT_DIR)
        else:
            print(
                "WARN: ML script not found in expected locations "
                f"({ml_candidates[0]}, {ml_candidates[1]}). Continuing without ML."
            )

    if run_clean_texts:
        run_step([args.python, "clean_texts.py", "--base", str(base)], "Clean extracted texts", SCRIPT_DIR)

    validate_cmd = [args.python, "validate_output.py", "--base", str(base)]
    if args.strict_validation:
        validate_cmd.append("--fail-on-warning")
    run_step(validate_cmd, "Validate outputs", SCRIPT_DIR)

    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()
