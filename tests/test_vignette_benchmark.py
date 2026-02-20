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

        self.assertEqual(summary.n_cases, 150)
        self.assertEqual(summary.red_flag_recall_baseline, 47.7)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.under_triage_rate_baseline, 47.4)
        self.assertEqual(summary.under_triage_rate_clinicaflow, 0.0)
        self.assertEqual(summary.over_triage_rate_baseline, 40.0)
        self.assertEqual(summary.over_triage_rate_clinicaflow, 0.0)


if __name__ == "__main__":
    unittest.main()
