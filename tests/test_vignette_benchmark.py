from __future__ import annotations

import unittest

from clinicaflow.benchmarks.vignettes import (
    load_default_vignette_path,
    load_default_vignette_paths,
    load_vignettes,
    run_benchmark,
    run_benchmark_rows,
)


class VignetteBenchmarkTests(unittest.TestCase):
    def test_vignette_regression_metrics_match_writeup(self) -> None:
        summary, per_case = run_benchmark(load_default_vignette_path())

        self.assertEqual(summary.n_cases, 30)
        self.assertEqual(summary.red_flag_recall_baseline, 87.5)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.under_triage_rate_baseline, 11.5)
        self.assertEqual(summary.under_triage_rate_clinicaflow, 0.0)
        self.assertEqual(summary.over_triage_rate_baseline, 50.0)
        self.assertEqual(summary.over_triage_rate_clinicaflow, 0.0)

        self.assertTrue(per_case)
        cf = per_case[0]["clinicaflow"]
        self.assertIn("safety_triggers", cf)
        self.assertIn("actions_added_by_safety", cf)
        self.assertIn("recommended_next_actions", cf)
        self.assertIn("action_provenance", cf)
        self.assertIn("workflow", cf)

    def test_vignette_extended_metrics_match_writeup(self) -> None:
        rows = []
        for p in load_default_vignette_paths("extended"):
            rows.extend(load_vignettes(p))
        summary, _ = run_benchmark_rows(rows)

        self.assertEqual(summary.n_cases, 100)
        self.assertEqual(summary.red_flag_recall_baseline, 30.3)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.under_triage_rate_baseline, 65.6)
        self.assertEqual(summary.under_triage_rate_clinicaflow, 0.0)
        self.assertEqual(summary.over_triage_rate_baseline, 30.0)
        self.assertEqual(summary.over_triage_rate_clinicaflow, 0.0)

    def test_vignette_mega_metrics_match_writeup(self) -> None:
        rows = []
        for p in load_default_vignette_paths("mega"):
            rows.extend(load_vignettes(p))
        summary, _ = run_benchmark_rows(rows)

        self.assertEqual(summary.n_cases, 174)
        self.assertEqual(summary.red_flag_recall_baseline, 53.3)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.under_triage_rate_baseline, 41.3)
        self.assertEqual(summary.under_triage_rate_clinicaflow, 0.0)
        self.assertEqual(summary.over_triage_rate_baseline, 47.4)
        self.assertEqual(summary.over_triage_rate_clinicaflow, 0.0)

    def test_vignette_realworld_metrics_match_writeup(self) -> None:
        rows = []
        for p in load_default_vignette_paths("realworld"):
            rows.extend(load_vignettes(p))
        summary, _ = run_benchmark_rows(rows)

        self.assertEqual(summary.n_cases, 24)
        self.assertEqual(summary.red_flag_recall_baseline, 90.0)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.under_triage_rate_baseline, 0.0)
        self.assertEqual(summary.under_triage_rate_clinicaflow, 0.0)
        self.assertEqual(summary.over_triage_rate_baseline, 75.0)
        self.assertEqual(summary.over_triage_rate_clinicaflow, 0.0)

    def test_vignette_case_reports_metrics_match_writeup(self) -> None:
        rows = []
        for p in load_default_vignette_paths("case_reports"):
            rows.extend(load_vignettes(p))
        summary, _ = run_benchmark_rows(rows)

        self.assertEqual(summary.n_cases, 50)
        self.assertEqual(summary.red_flag_recall_baseline, 44.0)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.under_triage_rate_baseline, 48.0)
        self.assertEqual(summary.under_triage_rate_clinicaflow, 0.0)
        self.assertEqual(summary.over_triage_rate_baseline, 0.0)
        self.assertEqual(summary.over_triage_rate_clinicaflow, 0.0)

    def test_vignette_ultra_metrics_match_writeup(self) -> None:
        rows = []
        for p in load_default_vignette_paths("ultra"):
            rows.extend(load_vignettes(p))
        summary, _ = run_benchmark_rows(rows)

        self.assertEqual(summary.n_cases, 224)
        self.assertEqual(summary.red_flag_recall_baseline, 51.0)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.under_triage_rate_baseline, 42.9)
        self.assertEqual(summary.under_triage_rate_clinicaflow, 0.0)
        self.assertEqual(summary.over_triage_rate_baseline, 47.4)
        self.assertEqual(summary.over_triage_rate_clinicaflow, 0.0)


if __name__ == "__main__":
    unittest.main()
