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


class QuantityCandidate(Strict):
    """One source's figure for one quantity.

    The unit of extraction is a *candidate*, not an answer. Three sources
    saying 341, 371 and 400 branches are three candidates, and the earlier
    schema had one `value` field - so the agent had to choose one and discard
    the disagreement, which is the opposite of triangulating. The spread and
    the vintage range are usually more informative than any single figure.

    The agent never averages, weights or reconciles these. domain/triangulate
    computes the band deterministically, so the arithmetic between three
    observations and one band is inspectable rather than a model's assertion.
    """
    # A string, parsed to a number by code. The field was Decimal, and a
    # domain whose honest answer is "2 halls, 2.75 MW" or "T-Systems (Deutsche
    # Telekom)" then failed the schema three times and wrote no disposition -
    # so the agent was punished for reporting what the source said. Prose here
    # is a real finding; it is simply not a quantity, and the difference is
    # decided deterministically rather than by refusing the reply.
    value: str
    unit: str | None = None
    source_url: str | None = None
    publisher: str | None = None
    as_of: str | None = None
    note: str | None = None


class Quantity(Strict):
    """A quantity the estimate can consume, and the candidates behind it.

    `label`, `country` and `unit` are free strings rather than enumerations
    because the vocabulary differs per domain and a wrong enumeration would
    force the model to mislabel rather than abstain. domain/promotion.py
    classifies them deterministically afterwards and declines what it cannot
    place - a visible refusal rather than a silent coercion.

    `value` remains the agent's single best reading, for the many cases where
    one source states one figure. Where several sources disagree, the agent
    lists them all in `candidates` and leaves the band to code.
    """
    label: str
    # As above: a string the code parses. A quantity that cannot be parsed is
    # kept as a qualitative finding rather than discarded, and never reaches
    # the estimate.
    value: str
    unit: str | None = None
    country: str | None = None
    bandwidth_mbps: int | None = None
    as_of: str | None = None
    candidates: list[QuantityCandidate] = Field(default_factory=list)


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


# ------------------------------------------------- public known-fact prefill
class ProposedKnownFact(Strict):
    """A fact the register could hold, found in public sources.

    A proposal, not a registration. It arrives with its sources attached,
    which is the difference that matters: an analyst asserting 400 branches
    from memory creates an uncorroborated assertion that caps confidence under
    0.6A, while the same figure arriving with two public sources behind it is
    already most of the way to being evidence.

    `value_low` and `value_high` exist because sources disagree, and a
    proposal that hides the disagreement to look tidier is the failure
    triangulation was built to stop. Where several figures were found, the
    band is stated and every source listed.
    """
    fact_class: str
    subject: str
    value_base: Decimal | None = None
    value_low: Decimal | None = None
    value_high: Decimal | None = None
    unit: str | None = None
    currency: str | None = None
    as_of: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: str | None = None
    note: str | None = None


class PublicFactSweep(Strict):
    facts: list[ProposedKnownFact] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    abstention_reason: AbstentionReason | None = None


# --------------------------------------------------------- entity confirmation
class EntityProfile(Strict):
    """A short, current profile of the subject, for a person to check against.

    Its only job is to let an analyst see whether the name they typed and the
    company the system is about to research are the same company. That check
    has failed twice in the field for the same reason: a registered legal name
    is often not what sources call the entity. "UniCredit Germany" is not a
    legal entity at all - the bank is UniCredit Bank GmbH and trades as
    HypoVereinsbank - and nothing surfaced that until every German source was
    quarantined as being about a different company.

    So `also_known_as` matters as much as the prose: it is offered straight
    into the case's entity_aliases, which is what the perimeter check and the
    search patterns read.

    Two paragraphs by design. Enough to recognise a company and notice when it
    is the wrong one; short enough that it is actually read.
    """
    legal_name_as_sources_state: str | None = None
    also_known_as: list[str] = Field(default_factory=list)
    country_of_domicile: str | None = None
    parent_or_group: str | None = None
    identifiers: list[str] = Field(default_factory=list)
    # Paragraph one: what this entity is. Legal form, ownership, what it does,
    # roughly how big, where.
    what_it_is: str | None = None
    # Paragraph two: what is currently true of it. Recent restructuring,
    # ownership changes, strategy, anything that would change how an estimate
    # about it should be read.
    what_is_current: str | None = None
    # Set when the supplied name could plausibly mean more than one entity -
    # a group versus its national subsidiary being the common case, and the
    # one that silently produces an estimate of the wrong perimeter.
    disambiguation_note: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    abstention_reason: AbstentionReason | None = None


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
