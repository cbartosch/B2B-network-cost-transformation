"""Typed outputs for every registered LLM service.

These replace the hand-written JSON shape strings that used to sit in domain
modules - `_RESPONSE_SHAPE`, `_PREFILL_SHAPE`, `_RECOMMEND_SHAPE` and the rest -
and the `parse_json_strict` calls that hand-checked a subset of their fields
afterwards. A shape described in prose is a shape nothing enforces: the model
was free to omit a field, invent one, or return a string where a number was
meant, and the first three of those failed silently.

Two conventions hold throughout:

**Abstention is typed.** A field the source does not support is null with an
`abstention_reason` drawn from a closed enumeration, never free text. Free text
cannot be aggregated, so a run where the agent quietly stopped finding things
looks exactly like a run where there was nothing to find.

**Nothing here carries authority.** No schema has a field for an evidence
state, a rights class, a confidence score the system will use, a coverage
figure or a monetary total. Where a model previously returned such a field -
corroboration state most notably - the field is absent from the schema, which
is a stronger control than validating it away afterwards.
"""
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    """Reject unknown fields.

    Provider-native strict schemas already forbid extra properties, but the
    two approved providers enforce that differently and a third would differ
    again. Enforcing it here means the guarantee holds whoever answered.
    """
    model_config = ConfigDict(extra="forbid")


class AbstentionReason(str, Enum):
    NOT_IN_SOURCE = "NOT_IN_SOURCE"
    SOURCE_AMBIGUOUS = "SOURCE_AMBIGUOUS"
    OUT_OF_PERIMETER = "OUT_OF_PERIMETER"
    CONFLICTING_SOURCES = "CONFLICTING_SOURCES"
    UNIT_UNRESOLVABLE = "UNIT_UNRESOLVABLE"
    RIGHTS_RESTRICTED = "RIGHTS_RESTRICTED"
    NO_SEARCH_RESULTS = "NO_SEARCH_RESULTS"


# --------------------------------------------------------------- LLM-01 / 08
class SourceRef(Strict):
    url: str
    publisher: str | None = None
    as_of: str | None = None


class Quantity(Strict):
    """A number the estimate can consume.

    `label`, `country` and `unit` are free strings rather than enumerations
    because the vocabulary differs per domain and a wrong enumeration would
    force the model to mislabel rather than abstain. domain/promotion.py
    classifies them deterministically afterwards and declines what it cannot
    place - a visible refusal rather than a silent coercion.
    """
    label: str
    value: Decimal
    unit: str | None = None
    country: str | None = None
    bandwidth_mbps: int | None = None
    as_of: str | None = None


class PublicEvidenceResult(Strict):
    found: bool
    subject: str | None = None
    finding: str | None = None
    quantities: list[Quantity] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    confidence_note: str | None = None
    abstention_reason: AbstentionReason | None = None


# ------------------------------------------------------------------- LLM-02
class QuestionnairePrefill(Strict):
    prefill_value: str | None = None
    basis: str | None = None
    abstention_reason: AbstentionReason | None = None


# ------------------------------------------------------------------- LLM-07
class ScenarioSelection(Strict):
    """Selection only.

    There is deliberately no field for a monetary amount. The advisory
    low/base/high are reloaded from the deterministic snapshot after
    selection; a model that cannot name a number cannot change one, which is
    a stronger guarantee than comparing an echoed value for equality.
    """
    scenario_code: str = Field(pattern="^[A-D]$")
    percentile: str = Field(pattern="^(low|base|high)$")
    basis: str


class AdvisoryNarrative(Strict):
    narrative: str


# --------------------------------------------------- known-fact corroboration
class CorroborationCandidate(Strict):
    url: str
    publisher: str | None = None
    as_of: str | None = None
    public_value: Decimal | None = None
    unit: str | None = None
    currency: str | None = None
    exact_excerpt: str | None = None
    comparison_notes: str | None = None


class CorroborationResult(Strict):
    """No state field, by construction.

    The model used to return CORROBORATED, UNCORROBORATED or CONTRADICTED and
    the system believed it - a model-authored evidence state, which is the
    defect the register rates P0. The schema has no place to put one, so the
    path cannot be reopened by an accommodating prompt.
    """
    candidates: list[CorroborationCandidate] = Field(default_factory=list)
    search_attempted: bool
    unresolved_reasons: list[str] = Field(default_factory=list)


# ------------------------------------------------------------ entity resolution
class EntityCandidate(Strict):
    """No match_score.

    Ordering and scoring are deterministic, from a versioned rule. A model
    supplying a score means candidate ranking changes when the model changes,
    which is neither reproducible nor auditable.
    """
    legal_name: str
    identifier: str | None = None
    identifier_type: str | None = None
    country_of_domicile: str | None = None
    website: str | None = None
    industry: str | None = None
    group_parent: str | None = None
    differentiators: list[str] = Field(default_factory=list)
    unresolved_attributes: list[str] = Field(default_factory=list)


class EntityResolutionResult(Strict):
    candidates: list[EntityCandidate] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------- LLM-09
class BenchmarkObservationOut(Strict):
    metric: str
    value: Decimal
    unit: str | None = None
    country: str | None = None
    product: str | None = None
    bandwidth_mbps: int | None = None
    vendor: str | None = None
    currency: str | None = None
    price_year: int | None = None
    term_months: int | None = None
    tax_basis: str | None = None
    sla_compliant: bool | None = None
    as_of: str | None = None
    raw_text: str | None = None
    inferred_fields: list[str] = Field(default_factory=list)
    confidence: str | None = None
    note: str | None = None


class BenchmarkExtractionResult(Strict):
    observations: list[BenchmarkObservationOut] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
