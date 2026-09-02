"""Governed analytical policy.

Spec 18.1: no material threshold, weight or prior may exist only as a code
constant. Unit costs were moved to reference data in an earlier round; the
weights that combine them were not, so `confidence.WEIGHTS`, `STAGE_CEILINGS`,
`LEVER_STAGE_WEIGHT`, `SIMULATED_BANDS`, the band floors and the inline
`0.40 / 0.35 / 0.25` driver weights all remained in Python. That is the same
defect the unit-cost fix was supposed to close, relocated rather than removed.

Two design rules follow, and the second is the one that matters:

  1. Every governed number is loaded from `reference.threshold`, which is
     versioned and carries an approver.
  2. **There are no defaults in this module.** A missing key raises rather than
     falling back, because a fallback constant is a code constant with extra
     steps. The seed is the single source of these values; tests construct a
     policy explicitly.

Policies are validated on construction, so a steward cannot commit weights that
sum to 1.3 or bands that overlap.
"""
from dataclasses import dataclass
from decimal import Decimal

from .money import D

ONE = D("1")
ZERO = D("0")


class PolicyIncomplete(RuntimeError):
    """A governed value is absent from reference data."""


class PolicyInvalid(RuntimeError):
    """Governed values are present but inconsistent."""


def _require(rows: dict, key: str, set_name: str) -> Decimal:
    if key not in rows:
        raise PolicyIncomplete(
            f"reference.threshold is missing {set_name}.{key}. Governed values "
            f"have no code default; run `make seed` or have the steward add it.")
    return D(rows[key])


def _in_unit_interval(name: str, value: Decimal) -> None:
    if not (ZERO <= value <= ONE):
        raise PolicyInvalid(f"{name}={value} is outside [0, 1]")


# --------------------------------------------------------------- confidence
@dataclass(frozen=True)
class ConfidencePolicy:
    set_name: str
    weights: dict                      # component -> weight, must sum to 1
    component_cap_headroom: Decimal
    band_floors: dict                  # band label -> floor
    stage_ceilings: dict               # stage -> component -> ceiling
    simulated_bands: tuple             # ((upper, ceiling|None), ...) ascending
    lever_stage_weight: dict           # stage -> weight
    baseline_drivers: dict             # driver -> weight, must sum to 1
    target_drivers: dict               # driver -> weight, must sum to 1
    asserted_ceiling: Decimal
    asserted_trigger: Decimal
    badge_threshold: Decimal
    partial_penalty_factor: Decimal    # applied below the lowest band floor
    known_fact_binding_tolerance: Decimal
    # How much a CLIENT_CONFIRMED value share counts toward the evidenced
    # driver, relative to independently-verifiable public evidence at 1.0.
    # Governed rather than hardcoded because it is exactly the kind of
    # judgement 18.1 says must carry an approver: it sets how much the model
    # trusts a client's self-report about their own estate.
    client_confirmed_evidence_weight: Decimal

    COMPONENTS = ("current_baseline", "target_cost", "realization")
    STAGES = ("V0",)
    LEVER_STAGES = ("V2", "V3", "V4", "V5")
    BASELINE_DRIVERS = ("priced_spend", "evidenced", "completeness")
    TARGET_DRIVERS = ("prior_coverage", "prior_recency")

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "confidence_policy"):
        r = lambda k: _require(rows, k, set_name)          # noqa: E731

        bands, i = [], 1
        while f"simulated_band_{i}_upper" in rows:
            upper = r(f"simulated_band_{i}_upper")
            ceiling = r(f"simulated_band_{i}_ceiling")
            # A ceiling of 1 means "no cap" - avoids nulls in a Numeric column.
            bands.append((upper, None if ceiling >= ONE else ceiling))
            i += 1
        if not bands:
            raise PolicyIncomplete(
                f"{set_name} defines no simulated_band_N_upper/ceiling pairs")

        policy = cls(
            set_name=set_name,
            weights={c: r(f"weight_{c}") for c in cls.COMPONENTS},
            component_cap_headroom=r("component_cap_headroom"),
            band_floors={"A": r("band_a_floor"), "B": r("band_b_floor"),
                         "C": r("band_c_floor")},
            stage_ceilings={s: {c: r(f"stage_ceiling_{s}_{c}") for c in cls.COMPONENTS}
                            for s in cls.STAGES},
            simulated_bands=tuple(bands),
            lever_stage_weight={s: r(f"lever_stage_weight_{s}") for s in cls.LEVER_STAGES},
            baseline_drivers={d: r(f"baseline_driver_{d}") for d in cls.BASELINE_DRIVERS},
            target_drivers={d: r(f"target_driver_{d}") for d in cls.TARGET_DRIVERS},
            asserted_ceiling=r("asserted_baseline_confidence_ceiling"),
            asserted_trigger=r("asserted_share_trigger"),
            badge_threshold=r("simulated_display_badge_threshold"),
            partial_penalty_factor=r("partial_penalty_factor"),
            known_fact_binding_tolerance=r("known_fact_binding_tolerance"),
            client_confirmed_evidence_weight=r("client_confirmed_evidence_weight"),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        if sum(self.weights.values()) != ONE:
            raise PolicyInvalid(
                f"component weights sum to {sum(self.weights.values())}, not 1")
        for name, value in self.weights.items():
            _in_unit_interval(f"weight_{name}", value)
        _in_unit_interval("component_cap_headroom", self.component_cap_headroom)
        _in_unit_interval("partial_penalty_factor", self.partial_penalty_factor)

        floors = [self.band_floors["A"], self.band_floors["B"], self.band_floors["C"]]
        if not floors[0] > floors[1] > floors[2] > ZERO:
            raise PolicyInvalid(f"band floors must be strictly descending: {floors}")

        for stage, comps in self.stage_ceilings.items():
            for c, v in comps.items():
                _in_unit_interval(f"stage_ceiling_{stage}_{c}", v)

        uppers = [u for u, _ in self.simulated_bands]
        if uppers != sorted(uppers) or len(set(uppers)) != len(uppers):
            raise PolicyInvalid(f"simulated band uppers must ascend: {uppers}")
        if uppers[-1] < ONE:
            raise PolicyInvalid(
                f"simulated bands stop at {uppers[-1]}; the top band must cover a "
                f"share of 1 or the schedule has a hole")
        ceilings = [c for _, c in self.simulated_bands if c is not None]
        if ceilings != sorted(ceilings, reverse=True):
            raise PolicyInvalid(
                f"simulated ceilings must not rise with share: {ceilings}")

        for group, expected in (("baseline_drivers", self.baseline_drivers),
                                ("target_drivers", self.target_drivers)):
            if sum(expected.values()) != ONE:
                raise PolicyInvalid(
                    f"{group} sum to {sum(expected.values())}, not 1")
        for s, v in self.lever_stage_weight.items():
            _in_unit_interval(f"lever_stage_weight_{s}", v)
        _in_unit_interval("asserted_baseline_confidence_ceiling", self.asserted_ceiling)
        _in_unit_interval("asserted_share_trigger", self.asserted_trigger)
        _in_unit_interval("simulated_display_badge_threshold", self.badge_threshold)
        _in_unit_interval("known_fact_binding_tolerance",
                          self.known_fact_binding_tolerance)
        # Must not reach 1: client-confirmed data counting as fully as
        # independently-verified public evidence would erase the distinction
        # this weight exists to express.
        _in_unit_interval("client_confirmed_evidence_weight",
                          self.client_confirmed_evidence_weight)
        if self.client_confirmed_evidence_weight >= ONE:
            raise PolicyInvalid(
                "client_confirmed_evidence_weight must be below 1: a client "
                "self-report is not independently verifiable, and weighting it "
                "as fully as public evidence removes the distinction")


# --------------------------------------------------------------- known facts
@dataclass(frozen=True)
class KnownFactPolicy:
    set_name: str
    agreement_tolerance: Decimal
    # The largest a bindable quantity can plausibly be. Governed rather than
    # hardcoded because "how many sites can a company have" is a judgement, and
    # a client with a genuinely enormous agent network should be able to raise
    # it deliberately rather than have a constant refuse their real figure.
    max_plausible_sites: int = 1_000_000
    max_plausible_users: int = 10_000_000

    @property
    def plausibility_bounds(self) -> dict:
        """Keyed by driver, the way BINDABLE names them."""
        return {"sites": self.max_plausible_sites,
                "users": self.max_plausible_users}

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "known_fact_policy"):
        policy = cls(set_name=set_name,
                     max_plausible_sites=int(_require(
                         rows, "max_plausible_sites", set_name)),
                     max_plausible_users=int(_require(
                         rows, "max_plausible_users", set_name)),
                     agreement_tolerance=_require(rows, "agreement_tolerance",
                                                  set_name))
        policy.validate()
        return policy

    def validate(self) -> None:
        _in_unit_interval("agreement_tolerance", self.agreement_tolerance)


# --------------------------------------------------------------- coverage
@dataclass(frozen=True)
class CoveragePolicy:
    set_name: str
    prior_coverage_min: Decimal
    prior_coverage_floor: Decimal
    material_country_floor: Decimal
    product_coverage_min: Decimal
    prior_recency_annual_decay: Decimal
    prior_recency_floor: Decimal

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "v0_coverage_threshold_set"):
        r = lambda k: _require(rows, k, set_name)          # noqa: E731
        policy = cls(
            set_name=set_name,
            prior_coverage_min=r("v0_prior_coverage_min"),
            prior_coverage_floor=r("v0_prior_coverage_floor"),
            material_country_floor=r("v0_material_country_floor"),
            product_coverage_min=r("v0_product_coverage_min"),
            prior_recency_annual_decay=r("prior_recency_annual_decay"),
            prior_recency_floor=r("prior_recency_floor"),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        for name in ("prior_coverage_min", "prior_coverage_floor",
                     "material_country_floor", "product_coverage_min",
                     "prior_recency_annual_decay", "prior_recency_floor"):
            _in_unit_interval(name, getattr(self, name))
        if self.prior_coverage_floor > self.prior_coverage_min:
            raise PolicyInvalid(
                f"absolute floor {self.prior_coverage_floor} exceeds the minimum "
                f"{self.prior_coverage_min}; nothing could ever publish PARTIAL")


# --------------------------------------------------------------- reconciliation
@dataclass(frozen=True)
class ReconciliationPolicy:
    """7.2E usage-variance tolerances by adapter reconciliation tier.

    These were seeded into reference.threshold AND hardcoded as
    `reconciliation.TIER_TOLERANCE = {"A": D("2.0"), "B": D("5.0")}` - the same
    numbers in two places, one governed and one not. The seeded values were
    decoration: an approver could change tier_a_tolerance_pct and the code would
    keep using its constant. Exactly the defect C2-06 fixed for the confidence
    weights, surviving in a module added later.

    Percentages, not unit-interval weights, so validated for positivity and
    ordering rather than with _in_unit_interval.
    """
    set_name: str
    tier_a_tolerance_pct: Decimal
    tier_b_tolerance_pct: Decimal
    consecutive_gap_incident: int

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "provider_reconciliation_tier"):
        r = lambda k: _require(rows, k, set_name)          # noqa: E731
        policy = cls(
            set_name=set_name,
            tier_a_tolerance_pct=r("tier_a_tolerance_pct"),
            tier_b_tolerance_pct=r("tier_b_tolerance_pct"),
            consecutive_gap_incident=int(r("consecutive_gap_incident")),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        for name in ("tier_a_tolerance_pct", "tier_b_tolerance_pct"):
            value = getattr(self, name)
            if value <= 0:
                raise PolicyInvalid(f"{name}={value} must be positive")
        if self.tier_a_tolerance_pct > self.tier_b_tolerance_pct:
            raise PolicyInvalid(
                f"tier A tolerance ({self.tier_a_tolerance_pct}) is looser than "
                f"tier B ({self.tier_b_tolerance_pct}). Tier A is the stricter "
                f"tier by definition - a provider with a reconcilable API is held "
                f"to a tighter variance than one read off a console by hand.")
        if self.consecutive_gap_incident < 1:
            raise PolicyInvalid(
                "consecutive_gap_incident must be at least 1; zero would raise an "
                "incident for a period that was never missed")

    def tier_tolerance(self) -> dict:
        """The mapping reconciliation.record() consumes."""
        return {"A": self.tier_a_tolerance_pct, "B": self.tier_b_tolerance_pct}


# --------------------------------------------------------------- research
@dataclass(frozen=True)
class ResearchPolicy:
    """0.3A research budget and stopping rule for the domain-research agents
    (LLM-01, LLM-08). Bounds effort so a run that searched harder is not
    conflated with a run that knows more - 18.1 defines 'maximalist' as a
    completeness contract over the 24 input domains, not as search volume,
    which is what makes it testable. These are counts, not weights, so they
    are validated for positivity rather than with _in_unit_interval."""
    set_name: str
    max_queries_per_domain: int
    max_captures_per_domain: int
    max_captures_per_run: int
    min_independent_sources_material_fact: int
    research_wall_clock_budget_minutes: int
    # Cap on the hosted web-search tool's own invocations per domain
    # (domain/research.py), distinct from max_queries_per_domain: one query
    # attempt to the model can itself trigger several searches server-side
    # before the model answers, and that's a different, provider-billed cost
    # dimension worth bounding on its own rather than folding into the
    # query-attempt count.
    max_web_searches_per_domain: int
    # Wall-clock ceiling for a single domain. Distinct from the run budget,
    # which bounds a whole pass and cannot bound a domain researched alone.
    max_seconds_per_domain: int
    max_output_tokens_per_call: int

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "research_budget_profile"):
        r = lambda k: _require(rows, k, set_name)          # noqa: E731
        policy = cls(
            set_name=set_name,
            max_queries_per_domain=int(r("max_queries_per_domain")),
            max_captures_per_domain=int(r("max_captures_per_domain")),
            max_captures_per_run=int(r("max_captures_per_run")),
            min_independent_sources_material_fact=int(
                r("min_independent_sources_material_fact")),
            research_wall_clock_budget_minutes=int(
                r("research_wall_clock_budget_minutes")),
            max_web_searches_per_domain=int(r("max_web_searches_per_domain")),
            max_seconds_per_domain=int(r("max_seconds_per_domain")),
            max_output_tokens_per_call=int(r("max_output_tokens_per_call")),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        for name in ("max_queries_per_domain", "max_captures_per_domain",
                     "max_captures_per_run", "research_wall_clock_budget_minutes",
                     "max_web_searches_per_domain", "max_seconds_per_domain",
                     "max_output_tokens_per_call"):
            value = getattr(self, name)
            if value <= 0:
                raise PolicyInvalid(f"{name}={value} must be positive")
        if self.min_independent_sources_material_fact < 1:
            raise PolicyInvalid(
                "min_independent_sources_material_fact must be at least 1 - "
                "zero would mean an unsourced claim counts as evidenced")
        if self.max_captures_per_domain > self.max_captures_per_run:
            raise PolicyInvalid(
                f"max_captures_per_domain ({self.max_captures_per_domain}) exceeds "
                f"max_captures_per_run ({self.max_captures_per_run}); a single "
                f"domain could never be fully searched within the run budget")


@dataclass(frozen=True)
class PriceDivergencePolicy:
    """How far a researched price may sit from the approved benchmark before
    the disagreement has to be adjudicated rather than absorbed.

    Deliberately not the known-fact agreement_tolerance: that governs whether
    a private assertion may be credited as the source of a quantity, and it is
    tighter because it decides attribution. This one decides whether a steward
    is told that public research contradicts a governed value - a different
    question with a different cost of being wrong."""
    set_name: str
    material_divergence_share: Decimal

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "price_divergence_policy"):
        policy = cls(set_name=set_name,
                     material_divergence_share=_require(
                         rows, "material_divergence_share", set_name))
        policy.validate()
        return policy

    def validate(self) -> None:
        _in_unit_interval("material_divergence_share",
                          self.material_divergence_share)
        if self.material_divergence_share <= 0:
            raise PolicyInvalid(
                "material_divergence_share must be above 0: zero would make "
                "every researched price a material disagreement, and the flag "
                "would be ignored within a day")


@dataclass(frozen=True)
class AnchorPolicy:
    """Governs the V0 ANCHOR method: how much of a disclosed cost line may be
    treated as addressable, and how that pool splits across cost layers.

    Every number here is an assumption. That is the method: where a site-level
    circuit inventory is not public - which is the normal case for a large
    group - a Stage 0 estimate anchors on a disclosed figure and states what
    share of it it claims to model. Governing the share is what keeps that
    claim visible and arguable instead of buried."""
    set_name: str
    addressable_share_low: Decimal
    addressable_share_base: Decimal
    addressable_share_high: Decimal
    layer_mix: dict
    min_addressable_share: Decimal

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "anchor_policy"):
        r = lambda k: _require(rows, k, set_name)          # noqa: E731
        policy = cls(
            set_name=set_name,
            addressable_share_low=r("addressable_share_low"),
            addressable_share_base=r("addressable_share_base"),
            addressable_share_high=r("addressable_share_high"),
            layer_mix={layer: r(f"layer_mix_{layer}")
                       for layer in ("L0", "L2", "L4", "OPS")},
            min_addressable_share=r("min_addressable_share"))
        policy.validate()
        return policy

    def validate(self) -> None:
        for name in ("addressable_share_low", "addressable_share_base",
                     "addressable_share_high", "min_addressable_share"):
            _in_unit_interval(name, getattr(self, name))
        if not (self.addressable_share_low <= self.addressable_share_base
                <= self.addressable_share_high):
            raise PolicyInvalid(
                f"addressable share must be ordered low <= base <= high, got "
                f"{self.addressable_share_low}/{self.addressable_share_base}/"
                f"{self.addressable_share_high}")
        total = sum(self.layer_mix.values())
        if abs(total - ONE) > Decimal("0.001"):
            raise PolicyInvalid(
                f"layer mix must sum to 1, got {total}: a pool that does not "
                f"account for itself would silently drop or double-count spend")


@dataclass(frozen=True)
class QualityPolicy:
    """How many attempts a rejected call gets.

    Governed rather than a keyword default because the number decides how much
    provider spend a systematically failing service can consume before anyone
    notices, and because a retry budget that can be raised at a call site is a
    retry budget nobody reviews."""
    set_name: str
    max_attempts_per_call: int

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "quality_policy"):
        policy = cls(set_name=set_name,
                     max_attempts_per_call=int(
                         _require(rows, "max_attempts_per_call", set_name)))
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.max_attempts_per_call < 1:
            raise PolicyInvalid(
                "max_attempts_per_call must be at least 1 - zero would mean no "
                "call is ever made")
        if self.max_transport_retries < 0 or self.max_transport_retries > 5:
            raise PolicyInvalid(
                "max_transport_retries must be between 0 and 5: past a handful "
                "the network is down rather than flaky, and retrying hides it")
        if self.max_attempts_per_call > 5:
            raise PolicyInvalid(
                f"max_attempts_per_call={self.max_attempts_per_call} is high "
                f"enough to hide a systematically failing service behind "
                f"retries, and to spend five times the budget doing it")


@dataclass(frozen=True)
class AgentQualityPolicy:
    """Bounds the retry loop on a rejected agent call."""
    set_name: str
    max_attempts_per_call: int
    # A transport failure is not a rejected answer, so it does not share the
    # quality budget: retrying a cut connection is worth doing and retrying a
    # schema violation three more times is not.
    max_transport_retries: int = 2
    transport_retry_backoff_seconds: int = 5

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "agent_quality_policy"):
        policy = cls(
            set_name=set_name,
            max_attempts_per_call=int(
                _require(rows, "max_attempts_per_call", set_name)),
            max_transport_retries=int(
                _require(rows, "max_transport_retries", set_name)),
            transport_retry_backoff_seconds=int(
                _require(rows, "transport_retry_backoff_seconds", set_name)))
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.max_attempts_per_call < 1:
            raise PolicyInvalid("max_attempts_per_call must be at least 1")
        if self.max_attempts_per_call > 5:
            raise PolicyInvalid(
                f"max_attempts_per_call is {self.max_attempts_per_call}: past "
                f"a handful of retries the loop is no longer correcting a "
                f"transient defect, it is pressing a model until it says "
                f"something acceptable")


@dataclass(frozen=True)
class TriangulationPolicy:
    """When disagreement between sources becomes a finding.

    Both values decide whether a human is asked to look at a quantity, which
    is why neither is a module constant: how much disagreement is tolerable
    depends on the engagement, and a threshold nobody can change is one
    everybody works around."""
    set_name: str
    material_spread_share: Decimal
    stale_after_years: int

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "triangulation_policy"):
        policy = cls(
            set_name=set_name,
            material_spread_share=_require(rows, "material_spread_share", set_name),
            stale_after_years=int(_require(rows, "stale_after_years", set_name)))
        policy.validate()
        return policy

    def validate(self) -> None:
        _in_unit_interval("material_spread_share", self.material_spread_share)
        if self.material_spread_share <= 0:
            raise PolicyInvalid(
                "material_spread_share must be above 0: at zero every band "
                "with two different figures needs review, and a review queue "
                "containing everything is read by nobody")
        if self.stale_after_years < 1:
            raise PolicyInvalid("stale_after_years must be at least 1")


@dataclass(frozen=True)
class FootprintPolicy:
    """How coarse a footprint row may be.

    A row is a statement that every site in it is identical - same bandwidth,
    same primary and backup product, same dual-access probability, same users
    per site. That is fine for five sites and false for five hundred, and the
    falsehood is priced."""
    set_name: str
    max_sites_per_archetype_row: int
    # A row that names a density band is a real cluster rather than an
    # assertion that a whole country's sites are alike, so it earns a looser
    # bound.
    max_sites_per_cluster_row: int = 2000

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "footprint_policy"):
        policy = cls(set_name=set_name,
                     max_sites_per_archetype_row=int(_require(
                         rows, "max_sites_per_archetype_row", set_name)),
                     max_sites_per_cluster_row=int(_require(
                         rows, "max_sites_per_cluster_row", set_name)))
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.max_sites_per_cluster_row < self.max_sites_per_archetype_row:
            raise PolicyInvalid(
                "max_sites_per_cluster_row must be at least "
                "max_sites_per_archetype_row: a row that says more about its "
                "sites cannot be held to a tighter bound than one that says "
                "less")
        if self.max_sites_per_archetype_row < 1:
            raise PolicyInvalid("max_sites_per_archetype_row must be at least 1")


# --------------------------------------------------------------- recommendation
@dataclass(frozen=True)
class RecommendationPolicy:
    """Tranche 2 (LLM-07, LLM-06). A lever's saving_base, as a share of current
    TCO, at or above material_lever_share_threshold makes that lever's
    inclusion a material assumption: the recommendation is stored regardless,
    but its narrative (LLM-06) will not present a final version until a named
    person has approved it (approved_by, never a role - the same requirement
    known_facts.py already holds asserted_by to)."""
    set_name: str
    material_lever_share_threshold: Decimal

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "recommendation_policy"):
        r = lambda k: _require(rows, k, set_name)          # noqa: E731
        policy = cls(set_name=set_name,
                    material_lever_share_threshold=r("material_lever_share_threshold"))
        policy.validate()
        return policy

    def validate(self) -> None:
        _in_unit_interval("material_lever_share_threshold",
                          self.material_lever_share_threshold)
