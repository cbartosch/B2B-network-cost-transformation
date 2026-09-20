#!/usr/bin/env python3
"""Run a list of companies through the whole chain, unattended.

Seventeen research domains at one to three minutes each is most of an hour per
company, so ten companies is an overnight job - and nobody should sit and watch
it. This drives the public API exactly as an analyst would and writes a row per
company when each finishes.

**It changes no application code and reaches into no internals.** Everything is
HTTP against endpoints the interface already uses, so a batch run cannot break
a case an analyst is working on, and a change to the API that breaks this is a
change that would have broken the interface too.

Resumable, because it will not survive contact with seventeen live provider
calls per company. Every completed step is written to the state file as it
lands, and a re-run skips what is already done rather than starting again - a
crash on company eight must not cost the seven before it.

One company at a time, one domain at a time. The API holds a worker for the
length of each research call, so two in parallel would queue behind each other
in the server and look like a hang from out here. `domain_nos` exists on the
research endpoint precisely so the caller can walk the list.

    python tools/run_batch.py companies.csv --out results.csv

The CSV needs `name` and `industry`; `countries` and `sites` are optional:

    name,industry,countries,sites
    AstraZeneca PLC,PHARMACEUTICALS,GB;SE;US,120
    Henkel AG,HOUSEHOLD_PERSONAL_CARE,DE;US;CN,180
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request


# Long, because a single research domain is a live provider call carrying a web
# search plus a fetch of every source it cites. The server's own ceiling is 480
# seconds; waiting less than that here would abandon calls that were going to
# succeed, which is the failure this whole tool exists to avoid.
READ_TIMEOUT = 600.0

# Between companies. Not politeness - it gives a cancelled or stuck run a
# moment to settle before the next case starts competing for the same worker.
BETWEEN_COMPANIES = 5.0


def _call(api, path, token, *, payload=None, method=None, timeout=READ_TIMEOUT):
    """One HTTP call. Raises on transport failure, returns the parsed body."""
    url = api.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method or ("POST" if data else "GET"))
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:400]
        raise RuntimeError(f"{method or 'POST'} {path} -> {exc.code}: "
                           f"{detail}") from exc


class State:
    """What has already been done, written as it happens.

    Flushed on every change rather than at the end: the whole point is to
    survive a process that does not reach the end.
    """

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.data = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text())
            except (OSError, ValueError):
                # A corrupt state file must not stop a run; it costs a repeat
                # of work already done, which is better than refusing to
                # start.
                print(f"  state file unreadable, starting fresh: {path}")
                self.data = {}

    def get(self, name: str) -> dict:
        return self.data.setdefault(name, {"steps": {}})

    def done(self, name: str, step: str) -> bool:
        """Completed, not merely attempted.

        A failed step was recorded as {"ok": False, ...} - truthy - so a
        re-run skipped it and the failure became permanent. The point of
        resuming is that somebody restarted after a crash, and a domain that
        failed on a timeout or a dropped connection should be tried again.

        A domain that fails for a permanent reason fails again and is recorded
        again, which costs one call and stays visible.
        """
        record = self.get(name)["steps"].get(step)
        if record is None or record is False:
            return False
        if isinstance(record, dict):
            return record.get("ok") is not False
        return bool(record)

    def mark(self, name: str, step: str, value=True) -> None:
        self.get(name)["steps"][step] = value
        self.flush()

    def flush(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))


def _create_case(api, token, row, state):
    """The case, or the one this run already made for this company."""
    name = row["name"]
    existing = state.get(name).get("case_id")
    if existing:
        return existing

    countries = [c.strip().upper() for c in
                 (row.get("countries") or "").split(";") if c.strip()]
    payload = {
        "subject_entity_legal_name": name,
        "industry": row.get("industry") or None,
        "in_scope_countries": countries,
        "country_of_domicile": countries[0] if countries else None,
        "base_currency": row.get("currency") or "USD",
        "price_year": int(row.get("price_year") or 2026),
        "engagement_purpose": "PROPOSAL_QUALIFICATION",
        "client_contact_status": "NO_CONTACT",
    }
    case = _call(api, "/v1/outside-in/cases", token, payload=payload,
                 timeout=60)
    case_id = case.get("case_id")
    state.get(name)["case_id"] = case_id
    state.flush()
    return case_id


def _research(api, token, case_id, name, state, domains):
    """One domain per call, recorded as each lands.

    A seventeen-domain run in one call is most of an hour of live provider
    work behind a single HTTP request, which no client should hold open - and
    a failure at domain fifteen would cost the fourteen before it.
    """
    for domain_no in domains:
        step = f"research:{domain_no}"
        if state.done(name, step):
            continue
        started = time.monotonic()
        try:
            _call(api, f"/v1/outside-in/cases/{case_id}/domain-research:run",
                  token, payload={"domain_nos": [domain_no],
                                  "overwrite": False})
            state.mark(name, step, {"ok": True,
                                    "seconds": round(time.monotonic() - started)})
            print(f"      domain {domain_no:>2} done in "
                  f"{int(time.monotonic() - started)}s")
        except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
            # Recorded and stepped over. A domain that could not be researched
            # is a gap the coverage gate already knows how to report, and one
            # failed domain must not cost the sixteen others.
            state.mark(name, step, {"ok": False, "error": str(exc)[:300]})
            print(f"      domain {domain_no:>2} FAILED: {str(exc)[:90]}")


def _simulate(api, token, case_id, name, state, footprint):
    """Queue the simulation and wait for it. 202 then poll, by design."""
    if state.done(name, "simulation"):
        return state.get(name)["steps"]["simulation"].get("run_id")

    queued = _call(api, f"/v1/outside-in/cases/{case_id}/simulations:run",
                   token, payload={"seed": 42, "ensemble_size": 25,
                                   "footprint": footprint}, timeout=60)
    run_id = queued.get("run_id") or queued.get("simulation_run_id")
    if not run_id:
        raise RuntimeError(f"no run id in {json.dumps(queued)[:200]}")

    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        run = _call(api, f"/v1/outside-in/simulations/{run_id}", token,
                    method="GET", timeout=60)
        status = (run.get("status") or "").upper()
        if status in ("SUCCEEDED", "COMPLETED", "DONE"):
            state.mark(name, "simulation", {"run_id": run_id})
            return run_id
        if status in ("FAILED", "CANCELLED", "ERROR"):
            raise RuntimeError(f"simulation {status}: "
                               f"{str(run.get('error'))[:200]}")
        time.sleep(5)
    raise RuntimeError("simulation did not finish within 15 minutes")


def _estimate(api, token, case_id, name, state):
    if state.done(name, "estimate"):
        return state.get(name)["steps"]["estimate"]
    result = _call(api, f"/v1/outside-in/cases/{case_id}/estimates:run",
                   token, payload={"method": "BUILD_UP"}, timeout=300)
    state.mark(name, "estimate", result)
    return result


def _footprint_for(row):
    """A single row the case can simulate from, or nothing.

    Deliberately thin. A batch run is not the place to invent an estate split:
    the footprint page exists to make a person choose one, and a plausible mix
    nobody decided would be priced as though someone had.
    """
    sites = row.get("sites")
    if not sites:
        return None
    countries = [c.strip().upper() for c in
                 (row.get("countries") or "").split(";") if c.strip()]
    if not countries:
        return None
    return [{"country": countries[0], "archetype": "LARGE_OFFICE",
             "density_band": "URBAN", "sites": int(sites)}]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("companies", help="CSV with name, industry, "
                                          "countries, sites")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--out", default="batch-results.csv")
    parser.add_argument("--state", default="batch-state.json",
                        help="resume file; delete it to start over")
    parser.add_argument("--domains", default="1-17",
                        help="which domains to research, e.g. 1-17 or 1,2,7")
    parser.add_argument("--skip-research", action="store_true",
                        help="simulation and estimate only - minutes rather "
                             "than hours, for checking the plumbing first")
    args = parser.parse_args()

    domains = []
    for part in args.domains.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            domains.extend(range(int(lo), int(hi) + 1))
        elif part.strip():
            domains.append(int(part))

    rows = list(csv.DictReader(pathlib.Path(args.companies).read_text()
                               .splitlines()))
    if not rows:
        print("no companies in that file")
        return 1

    state = State(pathlib.Path(args.state))
    print(f"{len(rows)} company(ies), "
          f"{0 if args.skip_research else len(domains)} domain(s) each")
    print(f"state: {args.state} - safe to stop and re-run\n")

    results = []
    for index, row in enumerate(rows, 1):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        print(f"[{index}/{len(rows)}] {name}")
        record = {"name": name, "industry": row.get("industry"),
                  "case_id": None, "status": "", "detail": ""}
        try:
            case_id = _create_case(args.api, args.token, row, state)
            record["case_id"] = case_id
            print(f"    case {case_id}")

            if not args.skip_research:
                _research(args.api, args.token, case_id, name, state, domains)

            footprint = _footprint_for(row)
            if footprint:
                _simulate(args.api, args.token, case_id, name, state,
                          footprint)
                print("    simulated")
                estimate = _estimate(args.api, args.token, case_id, name,
                                     state)
                cov = (estimate.get("coverage") or {})
                record["status"] = "ESTIMATED"
                record["coverage_status"] = cov.get("status")
                record["priced_share"] = cov.get("priced_share")
                record["total"] = ((estimate.get("current_tco") or {})
                                   .get("total"))
                print(f"    estimated: {record['total']}")
            else:
                # Researched and left for a person to allocate. Not a failure:
                # the footprint page exists to make somebody choose the split.
                record["status"] = "RESEARCHED_NO_FOOTPRINT"
                record["detail"] = ("no sites/countries given, so nothing was "
                                    "simulated - allocate the estate on "
                                    "page 5")
                print("    researched; no footprint to simulate")
        except Exception as exc:                        # noqa: BLE001
            # One company failing must not end the night. The state file holds
            # what succeeded, so a re-run resumes rather than repeats.
            record["status"] = "FAILED"
            record["detail"] = str(exc)[:300]
            print(f"    FAILED: {str(exc)[:120]}")

        results.append(record)
        # Written after every company, not at the end: a run that dies at
        # 3am should still have the rows it earned.
        fields = ["name", "industry", "case_id", "status", "coverage_status",
                  "priced_share", "total", "detail"]
        with open(args.out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        if index < len(rows):
            time.sleep(BETWEEN_COMPANIES)

    done = sum(1 for r in results if r["status"] == "ESTIMATED")
    print(f"\n{done} of {len(results)} estimated. Results: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
