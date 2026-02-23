from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ExternalEvidenceCitation:
    """A lightweight, linkable evidence citation from a free public API.

    This is intentionally minimal and demo-safe (no PHI). It is NOT a clinical
    knowledge base and should not be treated as validated guidance.
    """

    source: str
    source_id: str
    title: str
    citation: str
    url: str

    def to_protocol_citation(self) -> dict:
        """Return an object compatible with `protocol_citations` in EvidencePolicyAgent."""

        pid = f"{self.source.upper()}:{self.source_id}".strip(":")
        return {
            "policy_id": pid,
            "title": self.title,
            "citation": self.citation,
            "recommended_actions": [],
            "url": self.url,
            "source": self.source,
        }

    def to_dict(self) -> dict:
        return asdict(self)


SYMPTOM_EVIDENCE_QUERIES: dict[str, dict[str, str]] = {
    "chest pain": {"pubmed": "chest pain triage guideline", "medlineplus": "Chest pain"},
    "chest tightness": {"pubmed": "chest tightness acute coronary syndrome triage", "medlineplus": "Chest pain"},
    "shortness of breath": {"pubmed": "acute dyspnea triage hypoxemia", "medlineplus": "Shortness of breath"},
    "can't catch breath": {"pubmed": "acute dyspnea triage hypoxemia", "medlineplus": "Shortness of breath"},
    "slurred speech": {"pubmed": "stroke triage emergency evaluation", "medlineplus": "Stroke"},
    "weakness one side": {"pubmed": "stroke triage emergency evaluation", "medlineplus": "Stroke"},
    "word-finding difficulty": {"pubmed": "stroke triage emergency evaluation", "medlineplus": "Stroke"},
    "vomiting blood": {"pubmed": "upper gastrointestinal bleeding initial management", "medlineplus": "Vomiting blood"},
    "bloody stool": {"pubmed": "gastrointestinal bleeding initial management", "medlineplus": "Blood in stool"},
    "pregnancy bleeding": {"pubmed": "pregnancy bleeding emergency evaluation", "medlineplus": "Bleeding during pregnancy"},
    "severe headache": {"pubmed": "thunderclap headache emergency evaluation", "medlineplus": "Headache"},
    "fainting": {"pubmed": "syncope risk stratification emergency evaluation", "medlineplus": "Fainting"},
    "near-syncope": {"pubmed": "syncope risk stratification emergency evaluation", "medlineplus": "Fainting"},
    "fever": {"pubmed": "sepsis screening triage fever tachycardia", "medlineplus": "Fever"},
}


def build_evidence_queries(*, symptoms: list[str], differential: list[str]) -> dict[str, list[str]]:
    """Build safe, generic queries for free evidence APIs (no PHI)."""

    seen_pubmed: set[str] = set()
    seen_ml: set[str] = set()

    pubmed_queries: list[str] = []
    medlineplus_queries: list[str] = []

    for sym in symptoms or []:
        canonical = str(sym or "").strip().lower()
        if not canonical:
            continue
        hints = SYMPTOM_EVIDENCE_QUERIES.get(canonical)
        if hints:
            q_pub = str(hints.get("pubmed") or "").strip()
            q_ml = str(hints.get("medlineplus") or "").strip()
            if q_pub and q_pub not in seen_pubmed:
                seen_pubmed.add(q_pub)
                pubmed_queries.append(q_pub)
            if q_ml and q_ml not in seen_ml:
                seen_ml.add(q_ml)
                medlineplus_queries.append(q_ml)
            continue

        # Fallback: use the symptom text directly as a generic query seed.
        q_pub = f"{canonical} triage guideline".strip()
        q_ml = canonical.title()
        if q_pub not in seen_pubmed:
            seen_pubmed.add(q_pub)
            pubmed_queries.append(q_pub)
        if q_ml not in seen_ml:
            seen_ml.add(q_ml)
            medlineplus_queries.append(q_ml)

    # Add one differential seed if we have nothing.
    if not pubmed_queries and differential:
        top = str(differential[0] or "").strip()
        if top:
            pubmed_queries.append(f"{top} guideline")
    if not medlineplus_queries and differential:
        top = str(differential[0] or "").strip()
        if top:
            medlineplus_queries.append(top)

    crossref_queries = pubmed_queries[:] or [f"{str(differential[0]).strip()} guideline"] if differential else []
    crossref_queries = [str(q).strip() for q in crossref_queries if str(q).strip()]

    openalex_queries = crossref_queries[:]
    openalex_queries = [str(q).strip() for q in openalex_queries if str(q).strip()]

    clinicaltrials_queries: list[str] = []
    seen_trials: set[str] = set()
    for item in (symptoms or []) + (differential or []):
        q = str(item or "").strip()
        if not q:
            continue
        q = q[:120]
        key = q.lower()
        if key in seen_trials:
            continue
        seen_trials.add(key)
        clinicaltrials_queries.append(q)

    return {
        "pubmed": pubmed_queries[:3],
        "medlineplus": medlineplus_queries[:3],
        "crossref": crossref_queries[:3],
        "openalex": openalex_queries[:3],
        "clinicaltrials": clinicaltrials_queries[:3],
    }


PUBMED_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_ESEARCH_URL = PUBMED_EUTILS_BASE + "/esearch.fcgi"
PUBMED_ESUMMARY_URL = PUBMED_EUTILS_BASE + "/esummary.fcgi"
MEDLINEPLUS_WSEARCH_URL = "https://wsearch.nlm.nih.gov/ws/query"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
CLINICALTRIALS_V2_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"

_CACHE: dict[tuple[str, str, int], tuple[float, list[ExternalEvidenceCitation]]] = {}


def _cache_ttl_s() -> float:
    return max(0.0, _env_float("CLINICAFLOW_EVIDENCE_CACHE_TTL_S", 3600.0))


def _cache_get(source: str, query: str, limit: int) -> list[ExternalEvidenceCitation] | None:
    ttl = _cache_ttl_s()
    if ttl <= 0:
        return None
    key = (str(source or ""), str(query or "").strip().lower(), int(limit))
    now = time.time()
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, rows = hit
    if now - float(ts) > ttl:
        _CACHE.pop(key, None)
        return None
    return list(rows)


def _cache_put(source: str, query: str, limit: int, rows: list[ExternalEvidenceCitation]) -> None:
    ttl = _cache_ttl_s()
    if ttl <= 0:
        return
    key = (str(source or ""), str(query or "").strip().lower(), int(limit))
    _CACHE[key] = (time.time(), list(rows))


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def pubmed_search(*, query: str, limit: int, timeout_s: float) -> list[ExternalEvidenceCitation]:
    """Fetch PubMed citations via NCBI E-utilities (free; no API key required)."""

    q = str(query or "").strip()
    if not q:
        return []

    cached = _cache_get("pubmed", q, limit)
    if cached is not None:
        return cached

    tool = str(os.environ.get("CLINICAFLOW_EVIDENCE_PUBMED_TOOL", "clinicaflow") or "").strip()
    email = str(os.environ.get("CLINICAFLOW_EVIDENCE_PUBMED_EMAIL", "") or "").strip()

    params: dict[str, str] = {
        "db": "pubmed",
        "term": q,
        "retmode": "json",
        "retmax": str(max(1, int(limit))),
        "sort": "relevance",
    }
    if tool:
        params["tool"] = tool
    if email:
        params["email"] = email

    url = PUBMED_ESEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json"})  # noqa: S310

    with urllib.request.urlopen(req, timeout=max(0.5, float(timeout_s))) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))

    es = payload.get("esearchresult") if isinstance(payload, dict) else None
    idlist = es.get("idlist") if isinstance(es, dict) else None
    pmids = [str(x).strip() for x in idlist if str(x).strip()] if isinstance(idlist, list) else []
    pmids = pmids[: max(0, int(limit))]
    if not pmids:
        return []

    params2: dict[str, str] = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
    if tool:
        params2["tool"] = tool
    if email:
        params2["email"] = email
    url2 = PUBMED_ESUMMARY_URL + "?" + urllib.parse.urlencode(params2)
    req2 = urllib.request.Request(url=url2, method="GET", headers={"Accept": "application/json"})  # noqa: S310

    with urllib.request.urlopen(req2, timeout=max(0.5, float(timeout_s))) as resp:  # noqa: S310
        payload2 = json.loads(resp.read().decode("utf-8"))

    result = payload2.get("result") if isinstance(payload2, dict) else None
    if not isinstance(result, dict):
        return []

    citations: list[ExternalEvidenceCitation] = []
    uids = result.get("uids")
    ordered_pmids = [str(x).strip() for x in uids if str(x).strip()] if isinstance(uids, list) else pmids

    for pmid in ordered_pmids:
        row = result.get(pmid)
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        journal = str(row.get("fulljournalname") or row.get("source") or "").strip()
        pubdate = str(row.get("pubdate") or "").strip()
        year = pubdate[:4] if len(pubdate) >= 4 and pubdate[:4].isdigit() else ""
        cite = f"{journal} ({year}) PMID:{pmid}".strip()
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        citations.append(
            ExternalEvidenceCitation(
                source="pubmed",
                source_id=pmid,
                title=title or f"PubMed PMID {pmid}",
                citation=cite,
                url=url,
            )
        )
        if len(citations) >= limit:
            break

    _cache_put("pubmed", q, limit, citations)
    return citations


def medlineplus_search(*, term: str, limit: int, timeout_s: float) -> list[ExternalEvidenceCitation]:
    """Fetch MedlinePlus Health Topics via the NLM wsearch endpoint (free; no API key)."""

    t = str(term or "").strip()
    if not t:
        return []

    cached = _cache_get("medlineplus", t, limit)
    if cached is not None:
        return cached

    params = {"db": "healthTopics", "term": t, "retmax": str(max(1, int(limit))), "rettype": "brief"}
    url = MEDLINEPLUS_WSEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/xml"})  # noqa: S310

    with urllib.request.urlopen(req, timeout=max(0.5, float(timeout_s))) as resp:  # noqa: S310
        raw = resp.read()

    try:
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return []

    citations: list[ExternalEvidenceCitation] = []
    for doc in root.findall(".//document"):
        doc_id = str(doc.get("id") or "").strip()
        title = ""
        link = ""
        for content in doc.findall("content"):
            name = str(content.get("name") or "").strip().lower()
            value = "".join(content.itertext()).strip()
            if name == "title" and value:
                title = value
            elif name == "url" and value:
                link = value
        if not title or not link:
            continue
        citations.append(
            ExternalEvidenceCitation(
                source="medlineplus",
                source_id=doc_id or urllib.parse.quote_plus(title)[:32],
                title=title,
                citation="MedlinePlus Health Topics",
                url=link,
            )
        )
        if len(citations) >= limit:
            break
    _cache_put("medlineplus", t, limit, citations)
    return citations


def crossref_search(*, query: str, limit: int, timeout_s: float) -> list[ExternalEvidenceCitation]:
    """Fetch citations via Crossref works API (free; no API key)."""

    q = str(query or "").strip()
    if not q:
        return []

    cached = _cache_get("crossref", q, limit)
    if cached is not None:
        return cached

    params = {"query": q, "rows": str(max(1, int(limit)))}
    url = CROSSREF_WORKS_URL + "?" + urllib.parse.urlencode(params)

    # Crossref recommends identifying your tool in User-Agent.
    email = str(os.environ.get("CLINICAFLOW_EVIDENCE_PUBMED_EMAIL", "") or "").strip()
    ua = "clinicaflow"
    if email:
        ua = f"clinicaflow (mailto:{email})"

    req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json", "User-Agent": ua})  # noqa: S310
    with urllib.request.urlopen(req, timeout=max(0.5, float(timeout_s))) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))

    msg = payload.get("message") if isinstance(payload, dict) else None
    items = msg.get("items") if isinstance(msg, dict) else None
    if not isinstance(items, list):
        return []

    citations: list[ExternalEvidenceCitation] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        doi = str(item.get("DOI") or "").strip()
        title_raw = item.get("title")
        title = ""
        if isinstance(title_raw, list) and title_raw:
            title = str(title_raw[0] or "").strip()
        elif isinstance(title_raw, str):
            title = title_raw.strip()
        if not title:
            title = doi or "Crossref work"

        container_raw = item.get("container-title")
        container = ""
        if isinstance(container_raw, list) and container_raw:
            container = str(container_raw[0] or "").strip()
        year = ""
        issued = item.get("issued")
        if isinstance(issued, dict):
            parts = issued.get("date-parts")
            if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                y = parts[0][0]
                if isinstance(y, int):
                    year = str(y)
        cite = "Crossref"
        if container or year or doi:
            tail = " ".join([x for x in [container, f"({year})" if year else "", f"DOI:{doi}" if doi else ""] if x]).strip()
            cite = f"{tail}".strip() or cite
        url0 = str(item.get("URL") or "").strip()
        if not url0 and doi:
            url0 = f"https://doi.org/{doi}"

        source_id = doi or urllib.parse.quote_plus(title)[:40]
        citations.append(
            ExternalEvidenceCitation(
                source="crossref",
                source_id=source_id,
                title=title,
                citation=cite,
                url=url0,
            )
        )
        if len(citations) >= limit:
            break

    _cache_put("crossref", q, limit, citations)
    return citations


def openalex_search(*, query: str, limit: int, timeout_s: float) -> list[ExternalEvidenceCitation]:
    """Fetch citations via OpenAlex works search (free; no API key).

    OpenAlex is a general scholarly index. It is used as a backup evidence
    source when PubMed is unavailable.
    """

    q = str(query or "").strip()
    if not q:
        return []

    cached = _cache_get("openalex", q, limit)
    if cached is not None:
        return cached

    params = {"search": q, "per-page": str(max(1, int(limit)))}
    email = str(os.environ.get("CLINICAFLOW_EVIDENCE_PUBMED_EMAIL", "") or "").strip()
    if email:
        params["mailto"] = email

    url = OPENALEX_WORKS_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json", "User-Agent": "clinicaflow"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=max(0.5, float(timeout_s))) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []

    citations: list[ExternalEvidenceCitation] = []
    for item in results:
        if not isinstance(item, dict):
            continue

        oid = str(item.get("id") or "").strip()
        source_id = oid.rsplit("/", 1)[-1] if oid else ""

        doi_url = str(item.get("doi") or "").strip()
        doi_id = ""
        for prefix in ("https://doi.org/", "http://doi.org/"):
            if doi_url.startswith(prefix):
                doi_id = doi_url[len(prefix) :].strip()
                break

        title = str(item.get("title") or item.get("display_name") or "").strip()
        if not title:
            title = doi_id or source_id or "OpenAlex work"

        year_raw = item.get("publication_year")
        year = str(year_raw) if isinstance(year_raw, int) else ""

        venue = ""
        host = item.get("host_venue")
        if isinstance(host, dict):
            venue = str(host.get("display_name") or "").strip()

        cite_parts = []
        if venue:
            cite_parts.append(venue)
        if year:
            cite_parts.append(f"({year})")
        if doi_id:
            cite_parts.append(f"DOI:{doi_id}")
        cite = " ".join([p for p in cite_parts if p]).strip() or f"OpenAlex ({year})".strip() or "OpenAlex"

        url0 = doi_url or oid
        if not url0:
            continue

        citations.append(
            ExternalEvidenceCitation(
                source="openalex",
                source_id=source_id or (doi_id or urllib.parse.quote_plus(title)[:40]),
                title=title,
                citation=cite,
                url=url0,
            )
        )
        if len(citations) >= limit:
            break

    _cache_put("openalex", q, limit, citations)
    return citations


def clinicaltrials_search(*, query: str, limit: int, timeout_s: float) -> list[ExternalEvidenceCitation]:
    """Fetch trial links from ClinicalTrials.gov API v2 (free; no API key).

    This is a non-guideline backup source that can still provide relevant
    links when PubMed is unavailable.
    """

    q = str(query or "").strip()
    if not q:
        return []

    cached = _cache_get("clinicaltrials", q, limit)
    if cached is not None:
        return cached

    params = {"query.term": q, "pageSize": str(max(1, int(limit)))}
    url = CLINICALTRIALS_V2_STUDIES_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json", "User-Agent": "clinicaflow"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=max(0.5, float(timeout_s))) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))

    studies = payload.get("studies") if isinstance(payload, dict) else None
    if not isinstance(studies, list):
        return []

    citations: list[ExternalEvidenceCitation] = []
    for study in studies:
        if not isinstance(study, dict):
            continue

        proto = study.get("protocolSection")
        if not isinstance(proto, dict):
            continue
        ident = proto.get("identificationModule")
        if not isinstance(ident, dict):
            continue
        nct = str(ident.get("nctId") or "").strip()
        if not nct:
            continue

        title = str(ident.get("briefTitle") or ident.get("officialTitle") or "").strip()
        if not title:
            title = f"Clinical trial {nct}"

        status = ""
        status_module = proto.get("statusModule")
        if isinstance(status_module, dict):
            status = str(status_module.get("overallStatus") or "").strip()

        cite = f"ClinicalTrials.gov {nct}"
        if status:
            cite = f"{cite} ({status})"

        url0 = f"https://clinicaltrials.gov/study/{nct}"

        citations.append(
            ExternalEvidenceCitation(
                source="clinicaltrials",
                source_id=nct,
                title=title,
                citation=cite,
                url=url0,
            )
        )
        if len(citations) >= limit:
            break

    _cache_put("clinicaltrials", q, limit, citations)
    return citations


def collect_external_citations(
    *,
    backend: str,
    symptoms: list[str],
    differential: list[str],
    max_total: int | None = None,
    timeout_s: float | None = None,
) -> tuple[list[dict], dict]:
    """Collect external evidence citations as protocol-citation dicts.

    Returns: (protocol_citations, meta)
    """

    backend_raw = str(backend or "").strip().lower() or "local"
    timeout_s = float(timeout_s) if timeout_s is not None else _env_float("CLINICAFLOW_EVIDENCE_TIMEOUT_S", 2.5)
    max_total = int(max_total) if max_total is not None else _env_int("CLINICAFLOW_EVIDENCE_MAX_RESULTS", 3)
    max_total = max(0, min(int(max_total), 10))

    if backend_raw in {"", "local", "policy", "policy_pack", "none", "off", "disabled"}:
        return [], {"backend": "local", "ok": None, "error": "", "queries": {}}

    queries = build_evidence_queries(symptoms=symptoms, differential=differential)

    started = time.perf_counter()
    errors: list[str] = []
    citations: list[ExternalEvidenceCitation] = []

    def add_unique(rows: list[ExternalEvidenceCitation]) -> None:
        nonlocal citations
        seen = {f"{c.source}:{c.source_id}" for c in citations}
        for row in rows:
            key = f"{row.source}:{row.source_id}"
            if key in seen:
                continue
            seen.add(key)
            citations.append(row)
            if len(citations) >= max_total:
                break

    def try_pubmed() -> None:
        for q in queries.get("pubmed") or []:
            if len(citations) >= max_total:
                return
            try:
                add_unique(pubmed_search(query=q, limit=max_total - len(citations), timeout_s=timeout_s))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"pubmed:{q}: {exc}")

    def try_medlineplus() -> None:
        for q in queries.get("medlineplus") or []:
            if len(citations) >= max_total:
                return
            try:
                add_unique(medlineplus_search(term=q, limit=max_total - len(citations), timeout_s=timeout_s))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"medlineplus:{q}: {exc}")

    def try_crossref() -> None:
        for q in queries.get("crossref") or []:
            if len(citations) >= max_total:
                return
            try:
                add_unique(crossref_search(query=q, limit=max_total - len(citations), timeout_s=timeout_s))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"crossref:{q}: {exc}")

    def try_openalex() -> None:
        for q in queries.get("openalex") or []:
            if len(citations) >= max_total:
                return
            try:
                add_unique(openalex_search(query=q, limit=max_total - len(citations), timeout_s=timeout_s))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"openalex:{q}: {exc}")

    def try_clinicaltrials() -> None:
        for q in queries.get("clinicaltrials") or []:
            if len(citations) >= max_total:
                return
            try:
                add_unique(clinicaltrials_search(query=q, limit=max_total - len(citations), timeout_s=timeout_s))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"clinicaltrials:{q}: {exc}")

    if backend_raw == "pubmed":
        try_pubmed()
    elif backend_raw == "medlineplus":
        try_medlineplus()
    elif backend_raw == "crossref":
        try_crossref()
    elif backend_raw == "openalex":
        try_openalex()
    elif backend_raw == "clinicaltrials":
        try_clinicaltrials()
    elif backend_raw == "auto":
        try_pubmed()
        try_medlineplus()
        try_crossref()
        try_openalex()
        try_clinicaltrials()
    else:
        raise ValueError(f"Unsupported CLINICAFLOW_EVIDENCE_BACKEND: {backend_raw}")

    meta = {
        "backend": backend_raw,
        "ok": True if citations else False if errors else None,
        "error": "; ".join(errors[:3]),
        "queries": queries,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }

    out = [c.to_protocol_citation() for c in citations]
    return out, meta
