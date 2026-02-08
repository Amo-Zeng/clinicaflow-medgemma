# Synthetic Benchmark (Writeup Proxy)

The MedGemma Impact Challenge does not provide a dataset.
To keep results **reproducible** and avoid inflated claims, this repo includes a small synthetic benchmark used as a **proxy** for:

- red-flag detection robustness,
- under-triage avoidance,
- handoff completeness / documentation burden.

## Run it

Print the writeup table:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --print-markdown
```

Write a JSON summary:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --out results/synthetic_benchmark.json
```

## What it measures (definitions)

- **Red-flag recall**: among cases with at least one “true” red-flag trigger, the fraction where the system outputs any red-flag.
- **Unsafe recommendation rate** (proxy): fraction of cases whose true tier is urgent/critical but the system outputs `routine` (under-triage).
- **Handoff completeness** (0–5 proxy): counts whether key sections are produced (risk tier, red flags, differential, actions, patient summary).
- **Median triage write-up time**: derived proxy from completeness; higher completeness reduces a fixed documentation baseline.
- **Clinician usefulness** (0–5 proxy): simple heuristic based on completeness and under-triage penalties.

## Limitations

- Synthetic cases cannot substitute for real clinical validation.
- Metrics are proxies and should be interpreted as *workflow reliability signals*, not medical performance claims.
- Before any real deployment, evaluate on site-specific data distributions with clinical oversight.

