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
class SourceClass(str, Enum):
    """What kind of publisher this is. A factual classification, not a grade.

    The reliability grader used to infer this by matching keywords against the
    URL and publisher strings, which is crude and silently wrong for anything
    unfamiliar. The agent has already read the page and knows; asking it is
    both cheaper and better founded than guessing from a hostname.
    """
    PRIMARY_FILING = "PRIMARY_FILING"        # annual report, 10-K, prospectus
    REGULATOR = "REGULATOR"                  # regulator or statistics office
    COMPANY_PUBLISHED = "COMPANY_PUBLISHED"  # the entity's own site, ESG, IR
    TRADE_PRESS = "TRADE_PRESS"              # Reuters, FT, sector press
    AGGREGATOR = "AGGREGATOR"                # directories, profile sites
    OTHER = "OTHER"


class HowRead(str, Enum):
    """Whether the page was actually opened, or only its search snippet seen.

    A snippet is not worthless and it is not the same as having read the
    document. Reported so the grade can say which it was instead of treating
    them alike.
    """
    FULL_PAGE = "FULL_PAGE"
    SNIPPET_ONLY = "SNIPPET_ONLY"


class FigureBasis(str, Enum):
    """Whether the source states the figure or it was worked out from it."""
    STATED = "STATED"
    CALCULATED_FROM_STATED = "CALCULATED_FROM_STATED"
    INFERRED = "INFERRED"


# Free text is what fills a token budget, not list length.
#
# llm01 truncated at 8,000 tokens with 12 quantities and 6 candidates each -
# 72 candidates, every one carrying an unbounded excerpt, note and URL. That
# sizes at roughly 22,000 tokens, nearly three times the budget, and bounding
# the lists alone left it over.
#
# An excerpt is a short verbatim quote that proves a figure, not a paragraph.
# 160 characters is a sentence, which is what a quote needs to be - and it is
# what the copyright limits elsewhere in this system already assume.
EXCERPT_MAX = 160
NOTE_MAX = 120
LABEL_MAX = 120
# A URL long enough for a deep link into a filing, and short enough that
# seventy of them do not consume the reply. Four of the eight remaining
# unbounded fields in this model are URLs.
URL_MAX = 200


class SourceRef(Strict):
    url: str = Field(max_length=URL_MAX)
    publisher: str | None = None
    as_of: str | None = None
    # Provenance the agent observed. These are reports about the source, never
    # judgements about the finding: the grade is computed from them by code.
    source_class: SourceClass | None = None
    how_read: HowRead | None = None
    figure_basis: FigureBasis | None = None
    excerpt: str | None = Field(None, max_length=EXCERPT_MAX)


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
    source_url: str | None = Field(None, max_length=URL_MAX)
    publisher: str | None = None
    as_of: str | None = None
    note: str | None = Field(None, max_length=NOTE_MAX)
    # The same provenance SourceRef carries, because a candidate *is* one
    # source's figure. The base contract says "for every source, state
    # source_class, how_read and figure_basis" - the agent complied, put them
    # here, and this model's extra="forbid" rejected the whole reply with 26
    # validation errors. The instruction was right and the schema was wrong:
    # asking for a field and then refusing it is the worst of both.
    source_class: SourceClass | None = None
    how_read: HowRead | None = None
    figure_basis: FigureBasis | None = None
    excerpt: str | None = Field(None, max_length=EXCERPT_MAX)


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
    label: str = Field(max_length=LABEL_MAX)
    # As above: a string the code parses. A quantity that cannot be parsed is
    # kept as a qualitative finding rather than discarded, and never reaches
    # the estimate.
    value: str
    unit: str | None = None
    country: str | None = None
    bandwidth_mbps: int | None = None
    as_of: str | None = None
    # Dimensions the briefs ask for and the schema could not carry, so the
    # agent either dropped them or forced them into `label` where nothing
    # downstream could read them. A price without its currency and contract
    # term is not comparable with another price; a vendor signal without the
    # vendor is not a signal.
    currency: str | None = None
    vendor: str | None = None
    term_months: int | None = None
    technology: str | None = None
    candidates: list[QuantityCandidate] = Field(default_factory=list,
                                                max_length=4)
    # How many more sources stated this figure than could be returned. The
    # instruction is to list every one and not to average them; the cap is
    # what makes that finite, and this is what says the cap was reached.
    candidates_omitted: int = 0


class PublicEvidenceResult(Strict):
    found: bool
    subject: str | None = None
    finding: str | None = Field(None, max_length=1500)
    # Bounded, because the list nests: quantities x candidates grows
    # multiplicatively and truncated at 8,000 tokens after 114 seconds on the
    # company-profile domain. Raising the budget moves where it truncates; it
    # does not make an unbounded reply finite.
    #
    # The instruction to return every source and not to average them is right
    # and is kept - what it lacked was a ceiling and a way to say it had been
    # reached.
    quantities: list[Quantity] = Field(default_factory=list, max_length=10)
    # How many more the agent found and could not return. A thin answer
    # because the market is thin and a thin answer because the cap was hit are
    # different findings, and only the second is worth another call.
    # How many more the agent found and could not return. A thin answer
    # because the market is thin and a thin answer because the cap was hit are
    # different findings, and only the second is worth another call.
    quantities_omitted: int = 0
    sources: list[SourceRef] = Field(default_factory=list,
                                     max_length=10)
    confidence_note: str | None = Field(None, max_length=400)
    abstention_reason: AbstentionReason | None = None


# ------------------------------------------------------------------- LLM-02
class QuestionnairePrefill(Strict):
    prefill_value: str | None = None
    basis: str | None = None
    abstention_reason: AbstentionReason | None = None


# ------------------------------------------------- explaining an estimate
class EstimateAnswer(Strict):
    """An answer about a published estimate, and what it rests on.

    `answer` explains; it does not compute. Every figure in it must already be
    in the supplied packet - a number the snapshot does not contain is a
    fabrication however plausible, and an explanation of a cost model is
    exactly where one would be believed.

    `gaps_referenced` points at the deterministic gap list rather than
    restating it, so the recommendation an analyst acts on is the computed one.
    """
    answer: str
    # Which of the supplied gaps the answer is about, by their index in the
    # packet. Naming them keeps "what would improve this" tied to what was
    # actually measured as absent.
    gaps_referenced: list[int] = Field(default_factory=list)
    # Set when the packet does not contain what the question needs. Saying so
    # is the correct answer; inferring it is not.
    cannot_answer_from_packet: str | None = None
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


# How a source states a number it does not state precisely.
#
# AT_LEAST for "over 100" and "more than 5,000"; AT_MOST for "fewer than";
# APPROXIMATELY for "around" and "roughly"; EXACTLY when the source gives the
# figure plainly.
#
# A bound is not a worse figure than a point - it is a different claim, and
# reporting it as a point is the error. "Over 100 sites" read as 100 sites
# understates an estate by however much the word "over" was doing.
class ValueQualifier(str, Enum):
    EXACTLY = "EXACTLY"
    AT_LEAST = "AT_LEAST"          # "over 100", "more than 5,000"
    AT_MOST = "AT_MOST"            # "fewer than", "up to"
    APPROXIMATELY = "APPROXIMATELY"  # "around", "roughly", "circa"


# --------------------------------------------------- known-fact corroboration
class CorroborationCandidate(Strict):
    url: str
    publisher: str | None = None
    as_of: str | None = None
    # The provenance the base contract asks for on every source. Present on
    # every per-source model, because the contract does not say "except here" -
    # and a model that omits one rejects an agent for following instructions.
    source_class: SourceClass | None = None
    how_read: HowRead | None = None
    figure_basis: FigureBasis | None = None

    public_value: Decimal | None = None
    # How the source states the figure.
    #
    # A run failed closed on "over 100" three times: the agent found a source
    # saying "over 100 sites" and had nowhere to put the "over". That is a
    # lower bound, which is real evidence and the commonest way an annual
    # report states a count - "more than", "approximately", "in excess of".
    #
    # Coercing it to 100 drops the word and understates; rejecting it loses the
    # source entirely. Both are worse than recording the bound, and this model
    # already reasons in low/base/high everywhere else.
    #
    # Defaults to EXACTLY, so a reply that omits it is read as a precise figure
    # - which is what every reply before this one meant.
    value_qualifier: ValueQualifier = ValueQualifier.EXACTLY
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
    # The provenance the base contract asks for on every source. Present on
    # every per-source model, because the contract does not say "except here" -
    # and a model that omits one rejects an agent for following instructions.
    source_class: SourceClass | None = None
    how_read: HowRead | None = None
    figure_basis: FigureBasis | None = None
    excerpt: str | None = None
    confidence: str | None = None
    note: str | None = None


class NotFoundClass(Strict):
    """A fact class the sweep looked for and could not usably answer.

    `not_found` was list[str], and the prompt asked the agent to name the class
    "with what you searched for" - two things one string cannot hold. The
    agent's earlier replies put the reason inside the string, which reads
    correctly and parses as nothing, and after the instruction was tightened it
    returned an empty object three times rather than an unsatisfiable shape.
    Same defect as asking every source for a source_class the candidate schema
    forbade: the instruction was right and the schema was wrong.

    The reason is the useful part. "No public source isolates remote headcount
    from total headcount" tells an analyst the figure needs the client, which
    is a different next step from "nobody publishes this".
    """
    fact_class: str
    searched_for: str | None = None
    reason: str | None = None


class PublicFactSweep(Strict):
    facts: list[ProposedKnownFact] = Field(default_factory=list)
    not_found: list[NotFoundClass] = Field(default_factory=list)
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
    # How the source states the price, on the same terms as a corroboration
    # candidate.
    #
    # This feeds the rate card, and a tariff page is the likeliest place to
    # meet a qualified figure: "from GBP 250 a month", "up to 1 Gbps", "prices
    # start at". A Decimal with nowhere to put "from" fails the way
    # known_fact.corroborate failed on "over 100" - three attempts, all
    # rejected, and the observation lost.
    #
    # AT_LEAST is the common one here and it matters: an entry price read as a
    # market price understates the card, and the card is what every European
    # estate now derives from.
    value_qualifier: ValueQualifier = ValueQualifier.EXACTLY
    unit: str | None = None
    country: str | None = None
    product: str | None = None
    bandwidth_mbps: int | None = None
    vendor: str | None = None
    currency: str | None = None
    price_year: int | None = None
    term_months: int | None = None
    # A tariff usually offers a choice - "12, 24 or 36 months" - and the
    # observed price belongs to one of them. The longest is the one a headline
    # price is normally quoted against, so recording which was read stops a
    # 36-month price being normalised as though it were a 12-month one.
    term_months_basis: str | None = None
    tax_basis: str | None = None
    sla_compliant: bool | None = None
    as_of: str | None = None
    # The provenance the base contract asks for on every source. Present on
    # every per-source model, because the contract does not say "except here" -
    # and a model that omits one rejects an agent for following instructions.
    source_class: SourceClass | None = None
    how_read: HowRead | None = None
    figure_basis: FigureBasis | None = None
    excerpt: str | None = None
    raw_text: str | None = None
    inferred_fields: list[str] = Field(default_factory=list)
    confidence: str | None = None
    note: str | None = None


class BenchmarkExtractionResult(Strict):
    observations: list[BenchmarkObservationOut] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
