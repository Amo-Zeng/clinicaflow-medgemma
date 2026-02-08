from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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


@dataclass(slots=True)
class TriageResult:
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

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trace"] = [asdict(step) for step in self.trace]
        return payload


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
