#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_pipeline


class RunPipelineTests(unittest.TestCase):
    def test_parser_defaults(self):
        args = run_pipeline.build_parser().parse_args([])
        self.assertFalse(args.skip_ml)
        self.assertFalse(args.strict_validation)
        self.assertFalse(args.clean_texts)
        self.assertFalse(args.skip_clean_texts)

    def test_skip_ml_runs_only_analyze_and_validate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                with patch.object(run_pipeline, "run_step") as run_step:
                    with patch.object(sys, "argv", ["run_pipeline.py", "--skip-ml", "--base", "./albo_download"]):
                        run_pipeline.main()

                self.assertEqual(run_step.call_count, 2)
                analyze_cmd, analyze_label, _ = run_step.call_args_list[0].args
                validate_cmd, validate_label, _ = run_step.call_args_list[1].args

                self.assertEqual(analyze_label, "Analyze documents (pass 1)")
                self.assertEqual(validate_label, "Validate outputs")
                self.assertIn("--base", analyze_cmd)
                self.assertIn(str((run_pipeline.SCRIPT_DIR / "albo_download").resolve()), analyze_cmd)
                self.assertNotIn("--fail-on-warning", validate_cmd)
            finally:
                os.chdir(old_cwd)

    def test_clean_texts_opt_in(self):
        with patch.object(run_pipeline, "run_step") as run_step:
            with patch.object(sys, "argv", ["run_pipeline.py", "--skip-ml", "--clean-texts"]):
                run_pipeline.main()

        labels = [c.args[1] for c in run_step.call_args_list]
        self.assertIn("Clean extracted texts", labels)

    def test_skip_clean_texts_overrides_clean_texts(self):
        with patch.object(run_pipeline, "run_step") as run_step:
            with patch.object(
                sys,
                "argv",
                ["run_pipeline.py", "--skip-ml", "--clean-texts", "--skip-clean-texts"],
            ):
                run_pipeline.main()

        labels = [c.args[1] for c in run_step.call_args_list]
        self.assertNotIn("Clean extracted texts", labels)

    def test_strict_validation_flag_is_forwarded(self):
        with patch.object(run_pipeline, "run_step") as run_step:
            with patch.object(sys, "argv", ["run_pipeline.py", "--skip-ml", "--strict-validation"]):
                run_pipeline.main()

        validate_cmd, _, _ = run_step.call_args_list[-1].args
        self.assertIn("--fail-on-warning", validate_cmd)

    def test_ml_script_is_picked_from_custom_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "custom_base"
            base.mkdir(parents=True, exist_ok=True)
            (base / "randomForest.py").write_text("print('ok')", encoding="utf-8")

            with patch.object(run_pipeline, "run_step") as run_step:
                with patch.object(sys, "argv", ["run_pipeline.py", "--base", str(base)]):
                    run_pipeline.main()

            labels = [c.args[1] for c in run_step.call_args_list]
            self.assertIn("Train ML model", labels)


if __name__ == "__main__":
    unittest.main()
