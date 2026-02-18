from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class Vitals:
    heart_rate: float | None = None
    systolic_bp: float | None = None
    diastolic_bp: float | None = None
    temperature_c: float | None = None
    spo2: float | None = None
    respiratory_rate: float | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "Vitals":
        payload = payload or {}
        return cls(
            heart_rate=_to_float(payload.get("heart_rate")),
            systolic_bp=_to_float(payload.get("systolic_bp")),
            diastolic_bp=_to_float(payload.get("diastolic_bp")),
            temperature_c=_to_float(payload.get("temperature_c")),
            spo2=_to_float(payload.get("spo2")),
            respiratory_rate=_to_float(payload.get("respiratory_rate")),
        )


@dataclass(slots=True)
class PatientIntake:
    chief_complaint: str
    history: str = ""
    demographics: dict[str, Any] = field(default_factory=dict)
    vitals: Vitals = field(default_factory=Vitals)
    image_descriptions: list[str] = field(default_factory=list)
    prior_notes: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "PatientIntake":
        return cls(
            chief_complaint=str(payload.get("chief_complaint", "")).strip(),
            history=str(payload.get("history", "")).strip(),
            demographics=dict(payload.get("demographics", {})),
            vitals=Vitals.from_mapping(payload.get("vitals")),
            image_descriptions=[str(x) for x in payload.get("image_descriptions", [])],
            prior_notes=[str(x) for x in payload.get("prior_notes", [])],
        )

    def combined_text(self) -> str:
        sections = [self.chief_complaint, self.history, *self.prior_notes, *self.image_descriptions]
        return "\n".join(part.strip() for part in sections if part and part.strip())


@dataclass(slots=True)
class StructuredIntake:
    symptoms: list[str]
    risk_factors: list[str]
    missing_fields: list[str]
    normalized_summary: str


@dataclass(slots=True)
class AgentTrace:
    agent: str
    output: dict[str, Any]
    latency_ms: float | None = None
    error: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "AgentTrace":
        payload = payload or {}
        err = str(payload.get("error") or "").strip()
        return cls(
            agent=str(payload.get("agent") or "").strip(),
            output=dict(payload.get("output") or {}),
            latency_ms=_to_float(payload.get("latency_ms")),
            error=err or None,
        )


@dataclass(slots=True)
class TriageResult:
    run_id: str
    request_id: str
    created_at: str
    pipeline_version: str
    total_latency_ms: float
    risk_tier: str
    escalation_required: bool
    differential_considerations: list[str]
    red_flags: list[str]
    recommended_next_actions: list[str]
    clinician_handoff: str
    patient_summary: str
    confidence: float
    uncertainty_reasons: list[str]
    trace: list[AgentTrace]

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "TriageResult":
        payload = payload or {}
        trace_raw = payload.get("trace") or []
        trace = [AgentTrace.from_mapping(x) for x in trace_raw if isinstance(x, dict)]

        def clean_list(key: str) -> list[str]:
            values = payload.get(key) or []
            if not isinstance(values, list):
                return []
            return [str(x) for x in values if str(x).strip()]

        return cls(
            run_id=str(payload.get("run_id") or "").strip(),
            request_id=str(payload.get("request_id") or "").strip(),
            created_at=str(payload.get("created_at") or "").strip(),
            pipeline_version=str(payload.get("pipeline_version") or "").strip(),
            total_latency_ms=float(_to_float(payload.get("total_latency_ms")) or 0.0),
            risk_tier=str(payload.get("risk_tier") or "").strip().lower(),
            escalation_required=bool(payload.get("escalation_required")),
            differential_considerations=clean_list("differential_considerations"),
            red_flags=clean_list("red_flags"),
            recommended_next_actions=clean_list("recommended_next_actions"),
            clinician_handoff=str(payload.get("clinician_handoff") or "").strip(),
            patient_summary=str(payload.get("patient_summary") or "").strip(),
            confidence=float(_to_float(payload.get("confidence")) or 0.0),
            uncertainty_reasons=clean_list("uncertainty_reasons"),
            trace=trace,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trace"] = [asdict(step) for step in self.trace]
        return payload


def new_run_id() -> str:
    return uuid4().hex


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
