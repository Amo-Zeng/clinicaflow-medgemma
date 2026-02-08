from __future__ import annotations

import unittest

from clinicaflow.benchmarks.synthetic import run_benchmark


class SyntheticBenchmarkTests(unittest.TestCase):
    def test_seed_17_n220_matches_writeup(self) -> None:
        summary = run_benchmark(seed=17, n_cases=220)

        self.assertEqual(summary.red_flag_recall_baseline, 55.6)
        self.assertEqual(summary.red_flag_recall_clinicaflow, 100.0)
        self.assertEqual(summary.unsafe_rate_baseline, 22.7)
        self.assertEqual(summary.unsafe_rate_clinicaflow, 0.0)

        self.assertEqual(summary.median_writeup_time_min_baseline, 5.03)
        self.assertEqual(summary.median_writeup_time_min_clinicaflow, 4.26)

        self.assertEqual(summary.handoff_completeness_baseline, 2.52)
        self.assertEqual(summary.handoff_completeness_clinicaflow, 4.94)

        self.assertEqual(summary.usefulness_baseline, 3.11)
        self.assertEqual(summary.usefulness_clinicaflow, 4.76)


if __name__ == "__main__":
    unittest.main()

