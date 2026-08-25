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

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "known_fact_policy"):
        policy = cls(set_name=set_name,
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

    @classmethod
    def from_rows(cls, rows: dict, set_name: str = "research_policy"):
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
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        for name in ("max_queries_per_domain", "max_captures_per_domain",
                     "max_captures_per_run", "research_wall_clock_budget_minutes"):
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
