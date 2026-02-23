# Free Evidence APIs (Optional; No PHI)

ClinicaFlow’s **Evidence & Policy Agent** is local-first by default (policy pack only).
For demos, you can optionally attach additional citations from **free public APIs**.

Important:

- These sources are **best-effort** (network/rate limits/format drift).
- Do **not** send PHI to third-party endpoints. Keep `CLINICAFLOW_PHI_GUARD=1`.
- External citations are for *context* only and do not replace site protocols.

## Supported backends

Configured via:

```bash
CLINICAFLOW_EVIDENCE_BACKEND=local|pubmed|medlineplus|crossref|openalex|clinicaltrials|auto
```

### 1) `pubmed` (NCBI E-utilities)

- Endpoint family: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
- Used calls:
  - `esearch.fcgi` (find PMIDs)
  - `esummary.fcgi` (titles/journal/year)

Enable:

```bash
CLINICAFLOW_EVIDENCE_BACKEND=pubmed bash scripts/demo_one_click.sh
```

Optional (recommended etiquette; no secrets):

```bash
export CLINICAFLOW_EVIDENCE_PUBMED_TOOL=clinicaflow
export CLINICAFLOW_EVIDENCE_PUBMED_EMAIL='you@example.com'
```

### 2) `medlineplus` (NLM wsearch)

- Endpoint: `https://wsearch.nlm.nih.gov/ws/query`
- Database: `healthTopics`

Enable:

```bash
CLINICAFLOW_EVIDENCE_BACKEND=medlineplus bash scripts/demo_one_click.sh
```

### 3) `crossref` (Crossref works API)

General scholarly fallback (may be less clinically specific than PubMed):

```bash
CLINICAFLOW_EVIDENCE_BACKEND=crossref bash scripts/demo_one_click.sh
```

### 4) `openalex` (OpenAlex works API)

General scholarly index (backup when PubMed is unavailable):

```bash
CLINICAFLOW_EVIDENCE_BACKEND=openalex bash scripts/demo_one_click.sh
```

Optional (polite rate-limit handling):

```bash
export CLINICAFLOW_EVIDENCE_PUBMED_EMAIL='you@example.com'
```

### 5) `clinicaltrials` (ClinicalTrials.gov API v2)

Trial links as a non-guideline fallback source:

```bash
CLINICAFLOW_EVIDENCE_BACKEND=clinicaltrials bash scripts/demo_one_click.sh
```

### 6) `auto`

Tries `pubmed` → `medlineplus` → `crossref` → `openalex` → `clinicaltrials`:

```bash
CLINICAFLOW_EVIDENCE_BACKEND=auto bash scripts/demo_one_click.sh
```

## Tuning

```bash
export CLINICAFLOW_EVIDENCE_TIMEOUT_S=2.5
export CLINICAFLOW_EVIDENCE_MAX_RESULTS=3
export CLINICAFLOW_EVIDENCE_CACHE_TTL_S=3600
```

## Output shape

External citations are appended to `trace[].output.protocol_citations` with:

- `policy_id`: e.g., `PUBMED:12345`, `MEDLINEPLUS:42`
- `title`, `citation`
- `url` (clickable in Console UI + report.html)
- `recommended_actions`: empty list (safety/actions remain local-first)
