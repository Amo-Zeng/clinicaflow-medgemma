from __future__ import annotations

import json
import unittest
from unittest import mock

from clinicaflow.evidence import (
    ExternalEvidenceCitation,
    build_evidence_queries,
    clinicaltrials_search,
    collect_external_citations,
    crossref_search,
    medlineplus_search,
    openalex_search,
    pubmed_search,
)


class EvidenceTests(unittest.TestCase):
    def test_build_evidence_queries_is_phi_safe(self) -> None:
        queries = build_evidence_queries(symptoms=["chest pain"], differential=["Acute coronary syndrome"])
        self.assertIn("pubmed", queries)
        self.assertIn("medlineplus", queries)
        self.assertTrue(any("chest pain" in q.lower() for q in queries["pubmed"]))
        self.assertTrue(any("chest pain" in q.lower() for q in queries["medlineplus"]))

    def test_pubmed_search_parses_esearch_and_esummary(self) -> None:
        esearch_payload = {"esearchresult": {"idlist": ["12345"]}}
        esummary_payload = {
            "result": {
                "uids": ["12345"],
                "12345": {"title": "Example title", "fulljournalname": "Example Journal", "pubdate": "2024 Jan"},
            }
        }

        class _FakeResp:
            def __init__(self, payload: bytes) -> None:
                self._payload = payload

            def read(self) -> bytes:
                return self._payload

            def __enter__(self) -> "_FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
                return None

        def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:  # noqa: ANN001
            url = getattr(req, "full_url", "") or str(req)
            if "esearch.fcgi" in url:
                return _FakeResp(json.dumps(esearch_payload).encode("utf-8"))
            if "esummary.fcgi" in url:
                return _FakeResp(json.dumps(esummary_payload).encode("utf-8"))
            raise AssertionError(f"Unexpected URL: {url}")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            rows = pubmed_search(query="chest pain triage", limit=1, timeout_s=0.5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "pubmed")
        self.assertEqual(rows[0].source_id, "12345")
        self.assertIn("PMID:12345", rows[0].citation)
        self.assertTrue(rows[0].url.startswith("https://pubmed.ncbi.nlm.nih.gov/"))

    def test_medlineplus_search_parses_wsearch_xml(self) -> None:
        xml_payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <list>
    <document id="42">
      <content name="title">Chest pain</content>
      <content name="url">https://medlineplus.gov/chestpain.html</content>
    </document>
  </list>
</nlmSearchResult>
"""

        class _FakeResp:
            def read(self) -> bytes:
                return xml_payload

            def __enter__(self) -> "_FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
                return None

        def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:  # noqa: ANN001
            url = getattr(req, "full_url", "") or str(req)
            if "wsearch.nlm.nih.gov" not in url:
                raise AssertionError(f"Unexpected URL: {url}")
            return _FakeResp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            rows = medlineplus_search(term="Chest pain", limit=1, timeout_s=0.5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "medlineplus")
        self.assertEqual(rows[0].source_id, "42")
        self.assertEqual(rows[0].title, "Chest pain")
        self.assertTrue(rows[0].url.startswith("https://medlineplus.gov/"))

    def test_crossref_search_parses_json(self) -> None:
        payload = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/example",
                        "title": ["Example guideline title"],
                        "container-title": ["Example Journal"],
                        "issued": {"date-parts": [[2023, 1, 1]]},
                        "URL": "https://doi.org/10.1234/example",
                    }
                ]
            }
        }

        class _FakeResp:
            def read(self) -> bytes:
                return json.dumps(payload).encode("utf-8")

            def __enter__(self) -> "_FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
                return None

        def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:  # noqa: ANN001
            url = getattr(req, "full_url", "") or str(req)
            if "api.crossref.org/works" not in url:
                raise AssertionError(f"Unexpected URL: {url}")
            return _FakeResp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            rows = crossref_search(query="triage guideline", limit=1, timeout_s=0.5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "crossref")
        self.assertEqual(rows[0].source_id, "10.1234/example")
        self.assertEqual(rows[0].title, "Example guideline title")
        self.assertIn("DOI:10.1234/example", rows[0].citation)
        self.assertTrue(rows[0].url.startswith("https://"))

    def test_openalex_search_parses_json(self) -> None:
        payload = {
            "meta": {"count": 1, "page": 1, "per_page": 1},
            "results": [
                {
                    "id": "https://openalex.org/W2165065700",
                    "doi": "https://doi.org/10.1097/dmp.0b013e318182194e",
                    "title": "Mass Casualty Triage: A Proposed Guideline",
                    "publication_year": 2021,
                    "host_venue": {"display_name": "Disaster Medicine"},
                }
            ],
        }

        class _FakeResp:
            def read(self) -> bytes:
                return json.dumps(payload).encode("utf-8")

            def __enter__(self) -> "_FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
                return None

        def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:  # noqa: ANN001
            url = getattr(req, "full_url", "") or str(req)
            if "api.openalex.org/works" not in url:
                raise AssertionError(f"Unexpected URL: {url}")
            return _FakeResp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            rows = openalex_search(query="triage guideline", limit=1, timeout_s=0.5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "openalex")
        self.assertEqual(rows[0].source_id, "W2165065700")
        self.assertIn("DOI:10.1097/dmp.0b013e318182194e", rows[0].citation)
        self.assertTrue(rows[0].url.startswith("https://doi.org/"))

    def test_clinicaltrials_search_parses_json(self) -> None:
        payload = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Example trial title"},
                        "statusModule": {"overallStatus": "RECRUITING"},
                    }
                }
            ]
        }

        class _FakeResp:
            def read(self) -> bytes:
                return json.dumps(payload).encode("utf-8")

            def __enter__(self) -> "_FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
                return None

        def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:  # noqa: ANN001
            url = getattr(req, "full_url", "") or str(req)
            if "clinicaltrials.gov/api/v2/studies" not in url:
                raise AssertionError(f"Unexpected URL: {url}")
            return _FakeResp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            rows = clinicaltrials_search(query="triage", limit=1, timeout_s=0.5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "clinicaltrials")
        self.assertEqual(rows[0].source_id, "NCT00000001")
        self.assertIn("ClinicalTrials.gov", rows[0].citation)
        self.assertIn("RECRUITING", rows[0].citation)
        self.assertTrue(rows[0].url.startswith("https://clinicaltrials.gov/"))

    def test_collect_external_citations_returns_protocol_shape(self) -> None:
        fake = [
            ExternalEvidenceCitation(
                source="pubmed",
                source_id="1",
                title="A",
                citation="J (2024) PMID:1",
                url="https://pubmed.ncbi.nlm.nih.gov/1/",
            )
        ]

        with mock.patch("clinicaflow.evidence.pubmed_search", return_value=fake):
            citations, meta = collect_external_citations(
                backend="pubmed",
                symptoms=["chest pain"],
                differential=["Acute coronary syndrome"],
                max_total=1,
                timeout_s=0.5,
            )

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["policy_id"], "PUBMED:1")
        self.assertIn("url", citations[0])
        self.assertEqual(meta["backend"], "pubmed")


if __name__ == "__main__":
    unittest.main()
