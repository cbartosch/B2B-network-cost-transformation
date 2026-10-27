"""Every researched price beside the rate it would replace, for a steward.

    docker compose exec api sh -c 'cd /app && PYTHONPATH=/app \
        python tools/review_prices.py --out /src/samples/outside_in'

Writes price_review.json into --out, which tools/build_price_review.py turns
into the workbook a steward decides in. Read-only.

For each promoted price: its decision state, the figure in USD at the card's
own rates, the row it would replace or the tiers it would sit between,
whether approving it leaves the country's ladder monotonic, the evidence
research recorded for it, what other companies found for the same key, and
what its approval does to each sample baseline. For each country and
product: what approving every undecided price there would do, and what the
approvals already there are doing.

Effects are priced the way run_estimate prices, against the card as it
stands - so an approved price shows the effect it is having and an
undecided one the effect it would have. Nothing is reported until the
pricing has reproduced every stored L0 baseline to the cent: a review built
on pricing that does not match the estimate measures something else.

The first version of this was a set of scratch scripts that reviewed 59
prices once, against a card where none was decided - the same shape as the
committed sample review nothing could regenerate.
"""
import argparse
import csv
import json
import re
import sys
import types
from decimal import Decimal as D
from pathlib import Path

from sqlalchemy import select

from app import db
from app.domain import case_rates as case_rates_mod
from app.domain import currency, estimate, promotion
from app.domain.scope import REGION_PARENT, price_ladder

#: Wording that says what kind of price a figure is. Flags for the steward,
#: never decisions: a page saying "wholesale" may be quoting a retailer's
#: comparison, and only a person reading it can tell.
WORDING = {
    "wholesale": re.compile(r"wholesale|bitstream|l2-bsa|\bead\b|\bgea\b|"
                            r"openreach|vorleistung", re.I),
    "consumer": re.compile(r"consumer|residential|double-play|\bttc\b|"
                           r"incl\.? vat", re.I),
    "floor": re.compile(r"\bfrom (?:just |around |approximately )?[£€$]|"
                        r"\bstart(?:s|ing)? (?:at|from)|prices start", re.I),
    # "for 24 months ... thereafter" is Eir's, "during 12 months, then"
    # Proximus's: the introductory price and the one after it.
    "promotional": re.compile(r"promotion|promo\b|introductory|"
                              r"(?:for|during) \d+ months.{0,40}"
                              r"(?:then|thereafter)", re.I),
}


def ns(row, **over):
    data = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    data.update(over)
    return types.SimpleNamespace(**data)


def _json(value):
    if isinstance(value, (dict, list)) or value is None:
        return value
    try:
        return json.loads(value)
    except ValueError:
        return None


def inversions_in(tiers: dict) -> list:
    """Where a ladder of {tier: usd} costs less for more bandwidth.

    match_prior takes the cheapest tier AT OR ABOVE the need, so a cheap
    upper tier prices everything beneath it - right if the bigger plan is
    really cheaper, and the reason one approval can move many circuits.
    """
    seq = [(t, v) for t, v in sorted(tiers.items()) if v is not None]
    return [f"{a} Mbps at {va:.0f} > {b} Mbps at {vb:.0f} USD"
            for (a, va), (b, vb) in zip(seq, seq[1:]) if va > vb]


def flags_for(evidence: dict, *, fx_error, inversions, untraceable) -> list:
    """What a steward should look at first, from what is already known."""
    text = " ".join(filter(None, [
        evidence.get("label"), evidence.get("excerpt")]
        + [f"{s.get('excerpt') or ''} {s.get('note') or ''}"
           for s in evidence.get("sources") or []]))
    out = [name for name, pattern in WORDING.items() if pattern.search(text)]
    sources = evidence.get("sources") or []
    if len({s.get("source_url") for s in sources if s.get("source_url")}) <= 1:
        out.append("single source")
    if sources and all(s.get("how_read") == "SNIPPET_ONLY" for s in sources):
        out.append("read from a snippet")
    if untraceable:
        out.append("untraceable")
    if fx_error:
        out.append("no exchange rate")
    if inversions:
        out.append("re-prices lower tiers")
    return out


def traced(evidence: dict, url: str) -> tuple:
    """(evidence, untraceable) with a source a reviewer traced put first.

    The page was opened and the figure read on it, so the row is traceable
    whatever research stored - which, for a price whose disposition a later
    run replaced, is the run's narrative alone.
    """
    return {**evidence, "sources": [
        {"publisher": "traced in review", "source_url": url,
         "source_class": None, "how_read": "REVIEWER_TRACED",
         "excerpt": None, "note": None}]
        + list(evidence.get("sources") or [])}, False


class Review:
    """The card, the fifty sample companies, and pricing as the route does."""

    def __init__(self, out: Path, register: Path | None = None):
        self.out = out
        self._priced = {}
        # Sources a reviewer traced by hand, from the decisions register. The
        # stored evidence of a price whose disposition a later run replaced
        # is the run's narrative alone, so the tool flagged it untraceable for
        # good - Spain's DIA 600 included, after the audit had opened Direct
        # Telecom's page and read the figure on it.
        self.traced = {}
        if register is not None and register.exists():
            with open(register, encoding="utf-8") as f:
                self.traced = {line["id"]: line["traced_url"].strip()
                               for line in csv.DictReader(f)
                               if (line.get("traced_url") or "").strip()}
        with db.engine.connect() as s:
            self.card = [ns(r) for r in s.execute(
                select(db.unit_cost_prior)).all()]
            self.fx_rows = [
                {"from_currency": r.from_currency,
                 "to_currency": r.to_currency, "rate": r.rate,
                 "as_of": str(r.as_of) if r.as_of else None,
                 "convention": r.convention, "source": r.source,
                 "evidence_grade": r.evidence_grade}
                for r in s.execute(select(db.fx_rate)).all()]
            self.region_of = {r.country: r.region for r in s.execute(
                select(db.country_region)).all()}
            self.multipliers = {
                (m.product, m.density_band): {"low": m.low, "base": m.base,
                                              "high": m.high}
                for m in s.execute(select(db.density_cost_multiplier)).all()}
            self.slugs = json.loads((out / "_cases.json").read_text("utf-8"))
            cases = {r.case_id: r for r in s.execute(select(db.case).where(
                db.case.c.case_id.in_(list(self.slugs.values())))).all()}
            rates = {}
            for r in s.execute(select(db.case_rate)).all():
                rates.setdefault(r.case_id, []).append(
                    {"country": r.country, "service_class": r.service_class,
                     "access_technology": r.access_technology,
                     "bandwidth_mbps": r.bandwidth_mbps,
                     "monthly_recurring": str(r.monthly_recurring),
                     "currency": r.currency, "basis": r.basis,
                     "evidence_grade": r.evidence_grade,
                     "term_months": r.term_months,
                     "circuit_count": r.circuit_count})
            runs = [r.source_agent_run_id for r in self.card
                    if r.price_basis == "PROMOTED"]
            self.run_case = {r.agent_run_id: r.case_id for r in s.execute(
                select(db.agent_run.c.agent_run_id,
                       db.agent_run.c.case_id)).all()}
            self.dispositions = {}
            for d in s.execute(select(
                    db.domain_disposition.c.agent_run_id,
                    db.domain_disposition.c.domain_no,
                    db.domain_disposition.c.evidence).where(
                    db.domain_disposition.c.agent_run_id.in_(runs))).all():
                self.dispositions.setdefault(d.agent_run_id, []).append(d)
            self.narratives = {r.agent_run_id: _json(r.result) or {}
                               for r in s.execute(select(
                                   db.agent_run.c.agent_run_id,
                                   db.agent_run.c.result).where(
                                   db.agent_run.c.agent_run_id.in_(runs))).all()}
        self.slug_of = {v: k for k, v in self.slugs.items()}
        self.companies = {}
        for slug, case_id in self.slugs.items():
            sim = json.loads((out / slug / "simulation.json").read_text("utf-8"))
            est = json.loads((out / slug / "estimate_v0.json").read_text("utf-8"))
            # Only what L0 pricing reads. The estate list is most of each
            # file, and holding fifty of them ran a probe out of memory.
            self.companies[slug] = {
                "case": cases[case_id],
                "sim": {"products": sim["output"]["products"],
                        "sites": sim["output"].get("sites")},
                "stored": D(est["by_layer"]["L0"]["base"]),
                "rates": case_rates_mod.index(rates.get(case_id, []))}
        self.approved = [r for r in self.card if r.approved]
        self.promoted = sorted((r for r in self.card
                                if r.price_basis == "PROMOTED"),
                               key=lambda r: (r.country, r.product,
                                              r.bandwidth_mbps))
        self.observations = self._observations()

    # ------------------------------------------------------------ pricing
    def countries_of(self, slug):
        case, out = self.companies[slug]["case"], self.companies[slug]["sim"]
        return sorted(set(case.in_scope_countries or []) | {
            str(p["country"]) for p in out.get("products", [])
            if p.get("country")})

    def price_l0(self, slug, rows) -> tuple:
        """L0 base for one company, priced the way run_estimate prices it.

        Cached on the researched rows in play, which are all that differ
        between the cards this tool prices - the current one is the "before"
        of every undecided price.
        """
        key = (slug, frozenset((r.id, str(r.low), str(r.high))
                               for r in rows if r.price_basis == "PROMOTED"))
        if key not in self._priced:
            self._priced[key] = self._price_l0(slug, rows)
        return self._priced[key]

    def _price_l0(self, slug, rows) -> tuple:
        c = self.companies[slug]
        case, countries = c["case"], self.countries_of(slug)
        sub_of = {k: self.region_of[k] for k in countries
                  if k in self.region_of}
        subs = set(sub_of.values())
        scope = set(countries) | subs | {REGION_PARENT[r] for r in subs
                                         if r in REGION_PARENT}
        picked = estimate.best_priced_rows(
            [r for r in rows if r.country in scope])
        fx = currency.rate_table(
            self.fx_rows, currencies=[r.currency for r in picked],
            to=currency.normalise(case.base_currency),
            convention=getattr(case, "fx_convention", None),
            as_of=f"{case.price_year or 2026}-12-31")

        def prior(r):
            return {"low": r.low, "base": r.base, "high": r.high,
                    "price_year": r.price_year,
                    "expires": getattr(r, "expires", None),
                    "evidence_grade": getattr(r, "evidence_grade", None),
                    "price_basis": getattr(r, "price_basis", None),
                    "scope": r.country, "density_band": r.density_band,
                    "service_class": getattr(r, "service_class", None),
                    "access_technology": getattr(r, "access_technology",
                                                 None),
                    "currency": r.currency, "bandwidth_mbps": r.bandwidth_mbps}

        band = {(r.country, r.product, r.bandwidth_mbps,
                 (r.density_band or "").upper()): prior(r)
                for r in picked if r.density_band}
        priors = {(r.country, r.product, r.bandwidth_mbps): prior(r)
                  for r in picked if not r.density_band}
        for p in list(priors.values()) + list(band.values()):
            currency.convert_prior(p, factors=fx["factors"])
        estimate.reanchor_interpolated(priors)
        comps, _unpriced = estimate.build_components(
            sim_output=c["sim"], users=1,
            ops_cost_per_site={"low": D(0), "base": D(0), "high": D(0)},
            priors=priors, case_rates=c["rates"], band_priors=band,
            density_multipliers=self.multipliers,
            price_scopes={k: price_ladder(k, sub_of.get(k))
                          for k in countries})
        l0 = {x.key: x for x in comps if x.layer == "L0"}
        return sum((x.value.base for x in l0.values()), D(0)), l0

    def effect(self, country, with_rows, without_rows) -> dict:
        """Each company's L0 change from `without_rows` to `with_rows`."""
        out = {}
        for slug in self.companies:
            if country not in self.countries_of(slug):
                continue
            try:
                after, a = self.price_l0(slug, with_rows)
                before, b = self.price_l0(slug, without_rows)
            except currency.CurrencyMismatch as exc:
                out[slug] = {"error": str(exc)[:200]}
                continue
            if after == before:
                continue
            out[slug] = {
                "delta": str((after - before).quantize(D("0.01"))),
                "currency": self.companies[slug]["case"].base_currency,
                "circuits": sum(int(x.quantity) for k, x in a.items()
                                if k not in b
                                or x.value.base != b[k].value.base)}
        return out

    def reproduce(self) -> list:
        return [{"slug": slug, "stored": str(c["stored"]),
                 "reproduced": str(self.price_l0(slug, self.approved)[0]
                                   .quantize(D("0.01")))}
                for slug, c in self.companies.items()]

    # ------------------------------------------------------------ evidence
    def _observations(self) -> list:
        out = []
        for slug in self.slugs:
            path = self.out / slug / "research.json"
            if not path.exists():
                continue
            research = json.loads(path.read_text("utf-8"))
            for d in research.get("dispositions") or []:
                for q in ((d.get("evidence") or {}).get("quantities") or []):
                    product = promotion.product_in(q.get("label") or "")
                    if product and q.get("bandwidth_mbps"):
                        out.append({"slug": slug,
                                    "country": str(q.get("country")
                                                   or "").upper(),
                                    "product": product,
                                    "mbps": int(q["bandwidth_mbps"]),
                                    "value": q.get("value"),
                                    "currency": q.get("currency")})
        return out

    def evidence_for(self, p) -> tuple:
        """(the quantity research recorded for this row, untraceable?)"""
        for d in self.dispositions.get(p.source_agent_run_id, []):
            for q in ((_json(d.evidence) or {}).get("quantities") or []):
                if (str(q.get("country") or "").upper() == p.country
                        and promotion.product_in(q.get("label") or "")
                        == p.product
                        and int(q.get("bandwidth_mbps") or 0)
                        == int(p.bandwidth_mbps)):
                    return {"from": f"domain {d.domain_no} disposition",
                            "label": q.get("label"), "vendor": q.get("vendor"),
                            "term_months": q.get("term_months"),
                            "as_of": q.get("as_of"),
                            "sources": [{k: c.get(k) for k in (
                                "publisher", "source_url", "source_class",
                                "how_read", "excerpt", "note")}
                                for c in (q.get("candidates") or [])[:3]]}, False
        # A later rerun replaced the disposition. The run's own narrative is
        # what is left, searched for the figure as a whole number - "35"
        # inside "350" is not the figure.
        result = self.narratives.get(p.source_agent_run_id) or {}
        text = str(result.get("finding") or "")
        figure = f"{float(p.base):g}"
        hit = re.search(r"(?<![\d.,])" + re.escape(figure)
                        + r"(?:\.0+)?(?![\d,])", text)
        sources = result.get("verified_sources")
        return {"from": "run narrative (the disposition was replaced)",
                "label": None, "vendor": None, "term_months": None,
                "as_of": None,
                "excerpt": (text[max(0, hit.start() - 220): hit.end() + 160]
                            if hit else None),
                "sources": ([{"source_url": u} for u in sources[:3]]
                            if isinstance(sources, list) else [])}, hit is None

    # --------------------------------------------------------------- rows
    def usd(self, value, code):
        try:
            fx = currency.rate_table(self.fx_rows, currencies=[code],
                                     to="USD", convention=None,
                                     as_of="2026-12-31")
        except (currency.CurrencyMismatch, currency.UnknownCurrency) as exc:
            return None, str(exc)[:160]
        return D(str(value)) * fx["factors"][currency.normalise(code)], None

    def ladder(self, country, product, rows) -> dict:
        picked = estimate.best_priced_rows(
            [r for r in rows if r.country == country
             and r.product == product and not r.density_band])
        return {int(r.bandwidth_mbps): self.usd(r.base, r.currency)[0]
                for r in picked}

    @staticmethod
    def approved_as(p):
        """The row as approve_price would leave it, at its current band if it
        has one and the card's width if it is still a point."""
        if p.low != p.base or p.high != p.base:
            return ns({k: getattr(p, k) for k in vars(p)}, approved=True)
        width = promotion.CARD_BAND_SHARE
        return ns({k: getattr(p, k) for k in vars(p)}, approved=True,
                  low=D(str(p.base)) * (1 - width),
                  high=D(str(p.base)) * (1 + width))

    def price(self, p) -> dict:
        state = promotion.decision_on(p)
        usd, fx_error = self.usd(p.base, p.currency)
        others = [r for r in self.approved if r.id != p.id]
        replaced = estimate.best_priced_rows(
            [r for r in others if (r.country, r.product, r.bandwidth_mbps,
                                   r.density_band)
             == (p.country, p.product, p.bandwidth_mbps, None)
             and r.price_basis != "PROMOTED"])
        tiers = self.ladder(p.country, p.product, others)
        lower = max((t for t in tiers if t < p.bandwidth_mbps), default=None)
        upper = min((t for t in tiers if t > p.bandwidth_mbps), default=None)
        approved_ladder = self.ladder(p.country, p.product,
                                      others + [self.approved_as(p)])
        inversions = inversions_in(approved_ladder)
        evidence, untraceable = self.evidence_for(p)
        if p.id in self.traced:
            evidence, untraceable = traced(evidence, self.traced[p.id])
        effect = ({} if fx_error else self.effect(
            p.country, others + [self.approved_as(p)], others))
        note = p.source_note or ""
        return {
            "id": p.id, "country": p.country, "product": p.product,
            "mbps": int(p.bandwidth_mbps), "base": str(p.base),
            "currency": p.currency, "low": str(p.low), "high": str(p.high),
            "state": (state or {}).get("decision") or "UNDECIDED",
            "decided_by": (state or {}).get("by"),
            "usd": None if usd is None else str(usd.quantize(D("0.01"))),
            "replaces": (None if not replaced else {
                "id": replaced[0].id, "basis": replaced[0].price_basis,
                "usd": str(self.usd(replaced[0].base,
                                    replaced[0].currency)[0]
                           .quantize(D("0.01")))}),
            "lower_tier": lower, "upper_tier": upper,
            "inversions": inversions,
            "researched_by": self.slug_of.get(
                self.run_case.get(p.source_agent_run_id)),
            "as_of": (re.search(r"as_of ([^;]+);", note) or [None, None])[1],
            "evidence": evidence,
            "flags": flags_for(evidence, fx_error=fx_error,
                               inversions=inversions,
                               untraceable=untraceable),
            "other_observations": [
                {k: o[k] for k in ("slug", "value", "currency")}
                for o in self.observations
                if (o["country"], o["product"], o["mbps"])
                == (p.country, p.product, int(p.bandwidth_mbps))][:8],
            "effect": effect}

    def sets(self) -> list:
        """Each country and product: what is approved there, and what is not."""
        pairs = {}
        for p in self.promoted:
            pairs.setdefault((p.country, p.product), []).append(p)
        out = []
        for (country, product), group in sorted(pairs.items()):
            approved = [p for p in group if p.approved]
            # Held is undecided too: it does not price either.
            undecided = [p for p in group
                         if (promotion.decision_on(p) or {}).get("decision")
                         in (None, "HELD")]
            rest = [r for r in self.approved if r not in approved]
            out.append({
                "country": country, "product": product,
                "approved": [p.id for p in approved],
                "undecided": [p.id for p in undecided],
                "effect_of_approvals": (self.effect(country, self.approved,
                                                    rest)
                                        if approved else {}),
                "effect_of_approving_undecided": (self.effect(
                    country, self.approved
                    + [self.approved_as(p) for p in undecided],
                    self.approved) if undecided else {})})
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True,
                    help="the sample output directory; price_review.json is "
                         "written there")
    ap.add_argument("--register", default="",
                    help="the decisions register, for sources a reviewer "
                         "traced; defaults to price_decisions.csv beside the "
                         "output directory")
    args = ap.parse_args()
    out = Path(args.out)
    review = Review(out, Path(args.register) if args.register
                    else out.parent / "price_decisions.csv")

    checks = review.reproduce()
    off = [c for c in checks
           if abs(D(c["reproduced"]) - D(c["stored"])) > D("0.01")]
    if off:
        print(f"REFUSED: the pricing here reproduces {len(checks) - len(off)} "
              f"of {len(checks)} stored L0 baselines, so its effects would "
              f"measure something the estimate does not price. Re-run the "
              f"samples first. Off: "
              + ", ".join(f"{c['slug']} {c['reproduced']} vs {c['stored']}"
                          for c in off[:5]))
        return 1

    prices = []
    for p in review.promoted:
        prices.append(review.price(p))
        print(f"  {p.id}: {prices[-1]['state'].lower()}", flush=True)
    payload = {"reproduced": len(checks), "prices": prices,
               "sets": review.sets()}
    (out / "price_review.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), "utf-8")
    states = {}
    for p in prices:
        states[p["state"]] = states.get(p["state"], 0) + 1
    print(f"{len(prices)} researched price(s) "
          + ", ".join(f"{n} {k.lower()}" for k, n in sorted(states.items()))
          + f"; all {len(checks)} stored baselines reproduced -> "
            f"{out / 'price_review.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
