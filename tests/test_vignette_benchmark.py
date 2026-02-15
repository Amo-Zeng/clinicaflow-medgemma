from __future__ import annotations

import unittest

from clinicaflow.benchmarks.vignettes import load_default_vignette_path, run_benchmark


class VignetteBenchmarkTests(unittest.TestCase):
    def test_vignette_regression_metrics_match_writeup(self) -> None:
        summary, _ = run_benchmark(load_default_vignette_path())

        self.assertEqual(summary.n_cases, 30)
        self.assertEqual(summary.red_flag_recall_baseline, 87.5)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.under_triage_rate_baseline, 11.5)
        self.assertEqual(summary.under_triage_rate_clinicaflow, 0.0)
        self.assertEqual(summary.over_triage_rate_baseline, 50.0)
        self.assertEqual(summary.over_triage_rate_clinicaflow, 0.0)


if __name__ == "__main__":
    unittest.main()

