"""Research briefs: what each domain is actually asking for.

Held here as the seed source and stored in reference.research_brief, one row
per domain per version. The prompt reads the *stored* brief, not this module,
so a brief can be retuned without a rebuild - which matters because the brief
is the main lever on whether a domain finds anything, and the loop of read the
prompt, run the domain, adjust the wording is one an analyst runs, not an
engineer.

The first version of this module sent the domain *name* ("Location footprint")
and nothing else; the second added a sentence of description. Both produced
group-level prose and a homepage citation for entities that publish the answer
in their annual report, because neither told the agent how to hunt: what to
type into a search box, which documents carry this class of fact, what a
filled answer looks like, or what to throw away.

Keys, all optional except `asks`:
  asks    - the question, in one line
  wants   - the shape of a good answer: units, breakdowns, as-of dates
  search  - concrete query patterns. {entity} is substituted with the
            confirmed legal name; the agent is told to vary them, since a
            brand name usually out-searches a legal name ("DHL", not "DHL
            International GmbH")
  sources - named document types in rough priority order
  example - a filled `quantities` fragment, so the shape is shown rather
            than described
  reject  - what does not count, stated explicitly, because a plausible
            non-answer is worse than an abstention
"""

BRIEF_CATALOGUE_VERSION = "1.1.0"

RESEARCH_BRIEFS: dict[int, dict] = {
    # Each brief is a research instruction, not a label. The first version of
    # this module sent the domain *name* ("Location footprint") and nothing
    # else; the second added a sentence of description. Both produced
    # group-level prose and a homepage citation for entities that publish the
    # answer in their annual report, because neither told the agent how to
    # hunt: what to type into a search box, which documents carry this class
    # of fact, what a filled answer looks like, or what to throw away.
    #
    # Keys, all optional except `asks`:
    #   asks    - the question, in one line
    #   wants   - the shape of a good answer: units, breakdowns, as-of dates
    #   search  - concrete query patterns. {entity} is substituted with the
    #             confirmed legal name; the agent is told to vary them, since
    #             a brand name usually out-searches a legal name ("DHL", not
    #             "DHL International GmbH")
    #   sources - named document types in rough priority order
    #   example - a filled `quantities` fragment, so the shape is shown rather
    #             than described
    #   reject  - what does not count, stated explicitly, because a plausible
    #             non-answer is worse than an abstention
    1: {
        "asks": "What the entity is, at what scale, and where it operates.",
        "wants": "Revenue, employees, business segments, and the countries of "
                 "operation. Group versus the specific legal entity matters: "
                 "say which one each figure describes.",
        "search": ["{entity} annual report revenue employees",
                   "{entity} group structure segments",
                   "{entity} number of countries operations"],
        "sources": ["annual report or 20-F/10-K", "investor fact sheet",
                    "group company profile page"],
        "example": '[{"label": "revenue", "value": 84200000000, "unit": "EUR", '
                   '"as_of": "FY2024"}, {"label": "employees", "value": 594000, '
                   '"unit": "people", "as_of": "FY2024"}]',
    },
    2: {
        "asks": "How many physical sites the entity operates, by country and "
                "by site type - this drives the whole cost model, so it is the "
                "single most valuable domain to get right.",
        "wants": "Counts per country, each mapped to exactly one archetype. "
                 "Map by what the site DOES, not by what the sector calls it:\n"
                 "  DC - data centre or computing facility.\n"
                 "  LARGE_OFFICE - headquarters, regional office, campus, "
                 "operations centre.\n"
                 "  WAREHOUSE - a large operational or storage site: "
                 "distribution centre, depot, sorting hub, terminal, plant, "
                 "processing centre.\n"
                 "  STORE - a customer-facing outlet: retail shop, bank "
                 "branch, dealership, showroom, service point, agency, "
                 "pharmacy, restaurant.\n"
                 "  BRANCH - a small operational site that is not "
                 "customer-facing.\n"
                 "Where only a global total is published, give it and say it "
                 "is global. Always give the as-of date.",
        # Sector-neutral. The first version of this brief searched for "sorting
        # hubs" and "distribution centers" because it was written while looking
        # at a logistics company, and returned nothing for a bank - whose sites
        # are branches, Filialen, Geschaeftsstellen. The generic patterns run
        # first; the sector hint tells the agent to substitute the word its own
        # subject actually uses.
        "search": ["{entity} annual report number of locations",
                   "{entity} number of sites by country",
                   "{entity} branches offices locations count",
                   "{entity} sustainability report buildings floor area sites",
                   "{entity} store locator branch finder number of locations",
                   "{entity} Standorte Filialen Anzahl",
                   "{entity} facilities list country breakdown"],
        "sources": ["annual report - operations or segment section",
                    "ESG/sustainability report - buildings, energy or "
                    "emissions tables, which usually count sites by type",
                    "investor day or capital markets day presentation",
                    "the entity's own branch, store or location finder, and "
                    "its country subsidiary pages",
                    "sector regulators, which publish branch counts for banks, "
                    "pharmacies, and other licensed networks",
                    "business directories and registry listings",
                    "trade press covering openings and closures"],
        "example": '[{"label": "STORE", "value": 340, "unit": "sites", '
                   '"country": "DE", "as_of": "2024-12-31"}]',
        "reject": "A statement that the entity is 'a large European network' "
                  "or 'present in over 40 markets' is not a site count. Use "
                  "the word the subject's own sector uses - branch, Filiale, "
                  "depot, plant, store - rather than a word from a different "
                  "one. If you cannot find counts, say so rather than "
                  "restating scale.",
    },
    6: {
        "asks": "Data centres and cloud posture.",
        "wants": "Number of owned or co-located data centres and where they "
                 "are; named cloud providers and regions; any announced "
                 "consolidation, exit or migration with dates and targets.",
        "search": ["{entity} data center consolidation",
                   "{entity} AWS Azure Google Cloud migration press release",
                   "{entity} colocation Equinix Digital Realty",
                   "{entity} data centre strategy annual report"],
        "sources": ["cloud provider case study or press release naming the "
                    "entity", "annual report IT section",
                    "colocation provider customer announcements", "IT trade press"],
        "example": '[{"label": "DC", "value": 4, "unit": "sites", '
                   '"country": "DE", "as_of": "2024"}]',
    },
    7: {
        "asks": "What the wide-area network and network-security architecture "
                "looks like today.",
        "wants": "Which of MPLS, SD-WAN, internet breakout, DIA, broadband, "
                 "4G/5G backup, SASE/SSE, zero-trust, private cloud "
                 "interconnect are in use, and where. Name the products, not "
                 "just the categories. Note the year each claim describes: an "
                 "architecture statement from 2019 is not current state.",
        "search": ["{entity} SD-WAN deployment case study",
                   "{entity} MPLS network transformation",
                   "{entity} SASE SSE zero trust network",
                   "{entity} network architect job description SD-WAN",
                   "{entity} network modernization conference presentation"],
        "sources": ["network vendor case study naming the entity",
                    "carrier or MSP press release",
                    "conference talk or slide deck by the entity's network staff",
                    "job adverts requiring named products - weaker, but "
                    "attributable and dated",
                    "IT trade press"],
        "example": '[{"label": "sites on SD-WAN", "value": 1200, '
                   '"unit": "sites", "as_of": "2023"}]',
        "reject": "Vendor marketing describing what the entity *could* do, or "
                  "a generic industry trend piece that merely mentions the "
                  "entity, is not evidence of its architecture.",
    },
    8: {
        "asks": "Which network and security vendors, carriers and partners the "
                "entity actually uses.",
        "wants": "Named vendor and product per role: WAN carrier or carriers "
                 "by region, SD-WAN platform, firewall/SSE, managed service "
                 "provider, mobile operator. Say what each claim rests on and "
                 "how recent it is.",
        "search": ["{entity} selects network provider press release",
                   "{entity} managed network services contract awarded",
                   "{entity} Cisco Fortinet Palo Alto Zscaler Netskope customer",
                   "{entity} Orange Business BT Verizon Vodafone Telefonica contract",
                   "{entity} case study network"],
        "sources": ["vendor or carrier case study naming the entity - strongest",
                    "contract award or renewal press release",
                    "the entity's own procurement or supplier pages",
                    "job adverts naming products - weaker but dated"],
        "example": '[{"label": "WAN carrier", "value": 1, "unit": "named '
                   'supplier", "as_of": "2023"}]',
    },
    9: {
        "asks": "Published figures for what the entity spends on network, "
                "telecommunications or IT connectivity.",
        "wants": "An amount, a currency, a period, and - critically - which "
                 "reported line it came from and what that line includes. A "
                 "network-only figure is rare; an IT or technology cost line "
                 "is common and useful if labelled honestly.",
        "search": ["{entity} annual report IT costs technology expenses",
                   "{entity} telecommunications expenses segment report",
                   "{entity} IT spending million euros"],
        "sources": ["annual report notes - operating expenses breakdown",
                    "segment reporting", "investor presentations",
                    "analyst coverage quoting a spend figure"],
        "example": '[{"label": "IT and communications expense", '
                   '"value": 1800000000, "unit": "EUR", "as_of": "FY2024"}]',
        "reject": "Do not derive a network figure from a total IT figure here "
                  "- that belongs in domain 10 as an explicit proxy.",
    },
    10: {
        "asks": "A defensible proxy for IT or network spend where no direct "
                "figure is published.",
        "wants": "The proxy itself, its basis, and the arithmetic: total IT "
                 "spend, or IT spend as a percentage of revenue for this "
                 "sector from a named study, applied to the entity's revenue. "
                 "State the source of the ratio.",
        "search": ["logistics industry IT spend percentage of revenue",
                   "transportation sector IT budget benchmark Gartner",
                   "{entity} revenue annual report"],
        "sources": ["analyst benchmark studies naming the sector",
                    "industry association reports", "the entity's revenue "
                    "from its own accounts"],
        "example": '[{"label": "IT spend proxy", "value": 1260000000, '
                   '"unit": "EUR", "as_of": "FY2024"}]',
    },
    12: {
        "asks": "Telecom, network and managed-service contracts and sourcing "
                "events.",
        "wants": "Counterparty, scope, value, duration and date for each "
                 "award, renewal, tender or framework agreement. Public-sector "
                 "tender portals carry these verbatim where the entity or its "
                 "subsidiaries are in scope.",
        "search": ["{entity} network services tender award",
                   "{entity} telecommunications contract renewal",
                   "{entity} RFP wide area network",
                   "{entity} framework agreement connectivity"],
        "sources": ["tender and procurement portals - TED for the EU, "
                    "national equivalents elsewhere",
                    "carrier and MSP contract-win press releases",
                    "trade press covering deal values"],
        "example": '[{"label": "contract value", "value": 45000000, '
                   '"unit": "EUR", "as_of": "2023"}, {"label": "contract term", '
                   '"value": 5, "unit": "years", "as_of": "2023"}]',
    },
    13: {
        "asks": "Publicly reported outages or performance incidents affecting "
                "the entity's network or IT.",
        "wants": "Date, duration, what failed, and any stated operational or "
                 "financial impact.",
        "search": ["{entity} IT outage disruption",
                   "{entity} systems failure delays statement",
                   "{entity} cyber incident network"],
        "sources": ["the entity's own incident statements",
                    "regulatory disclosures", "established trade and news press"],
    },
    14: {
        "asks": "Announced transformation programmes touching network, IT "
                "infrastructure or cost reduction.",
        "wants": "Programme name, stated budget, savings target, timeline and "
                 "scope. Investor days are where these get quantified.",
        "search": ["{entity} digital transformation strategy investor day",
                   "{entity} cost savings programme IT infrastructure",
                   "{entity} strategy 2030 digitalization targets"],
        "sources": ["investor day and capital markets day decks",
                    "results presentations", "annual report strategy section"],
        "example": '[{"label": "announced IT savings target", '
                   '"value": 500000000, "unit": "EUR", "as_of": "2025-2030"}]',
    },
    15: {
        "asks": "Direction and rate of change in the site estate.",
        "wants": "Openings, closures, consolidations, acquisitions and "
                 "disposals, with counts and dates - enough to say whether the "
                 "estate is growing or shrinking and how fast.",
        "search": ["{entity} opens new distribution center",
                   "{entity} closes facilities consolidation",
                   "{entity} acquisition logistics network expansion"],
        "sources": ["press releases", "annual report operations section",
                    "regional and trade press"],
        "example": '[{"label": "sites opened", "value": 25, "unit": "sites", '
                   '"as_of": "FY2024"}]',
    },
    16: {
        "asks": "Regulatory and data-sovereignty constraints shaping where "
                "traffic and data may travel.",
        "wants": "Sector regulation, national data-residency rules and any "
                 "localisation commitments the entity has made, for the "
                 "in-scope countries specifically.",
        "search": ["{entity} data protection data residency commitment",
                   "data localisation requirements {country} enterprise",
                   "{entity} GDPR compliance data transfers"],
        "sources": ["the entity's privacy and compliance disclosures",
                    "national regulators", "law-firm country guides"],
    },
    18: {
        "asks": "Whether enterprise connectivity can actually be delivered in "
                "the in-scope countries, and by whom.",
        "wants": "Per in-scope country: incumbent and credible alternative "
                 "carriers, availability of DIA, MPLS, ethernet and business "
                 "broadband, typical lead times, and any country where "
                 "provisioning is materially constrained.",
        "search": ["enterprise fibre availability {country} business carriers",
                   "{country} telecom market incumbent alternative operators",
                   "leased line availability lead time {country}"],
        "sources": ["national telecom regulator market reviews",
                    "carrier coverage and product pages",
                    "ITU or OECD market data"],
        "example": '[{"label": "credible enterprise carriers", "value": 4, '
                   '"unit": "operators", "country": "DE", "as_of": "2025"}]',
    },
    19: {
        "asks": "Market unit prices for enterprise connectivity in the "
                "in-scope countries.",
        "wants": "Monthly recurring charge per circuit by product (DIA, MPLS, "
                 "ETHERNET, BROADBAND, MOBILE_5G) and bandwidth, per country, "
                 "with currency and price year. This feeds the pricing "
                 "benchmark directly, so precision matters more than coverage.",
        "search": ["{country} leased line pricing benchmark enterprise",
                   "dedicated internet access price per Mbps {country}",
                   "regulator broadband business tariff comparison {country}",
                   "MPLS circuit monthly cost benchmark"],
        "sources": ["national regulator price benchmarking studies",
                    "published carrier business tariffs",
                    "analyst pricing studies - TeleGeography and similar"],
        "example": '[{"label": "DIA 100Mbps MRC", "value": 520, "unit": "USD/'
                   'month", "country": "DE", "as_of": "2025"}]',
        "reject": "Consumer broadband pricing is not an enterprise circuit "
                  "price. Say which market a price describes.",
    },
    20: {
        "asks": "Customary contract lengths and commercial terms for "
                "enterprise network services in these markets.",
        "wants": "Typical term, notice period, and whether early-termination "
                 "charges are customary.",
        "search": ["enterprise connectivity contract term typical years",
                   "leased line minimum term early termination charge",
                   "{country} business telecom contract terms regulation"],
        "sources": ["carrier standard terms", "regulator consumer/business "
                    "contract rules", "analyst market practice notes"],
        "example": '[{"label": "typical contract term", "value": 3, '
                   '"unit": "years", "country": "DE", "as_of": "2025"}]',
    },
    21: {
        "asks": "One-off costs of a network transformation of this shape.",
        "wants": "Migration cost per site, professional services, parallel "
                 "running and decommissioning - ideally from a published "
                 "comparable programme, with the estate size it covered so the "
                 "figure can be normalised.",
        "search": ["SD-WAN migration cost per site enterprise",
                   "network transformation programme cost case study",
                   "WAN refresh professional services cost benchmark"],
        "sources": ["analyst studies", "vendor case studies stating programme "
                    "cost and site count", "published public-sector business "
                    "cases, which often disclose full costs"],
        "example": '[{"label": "migration cost per site", "value": 2200, '
                   '"unit": "USD", "as_of": "2024"}]',
    },
    22: {
        "asks": "Currency, inflation and tax parameters for the in-scope "
                "countries.",
        "wants": "FX rates against the case base currency for the price year, "
                 "telecom-specific taxes or levies, and recent inflation in "
                 "business services.",
        "search": ["{country} telecom tax levy business services",
                   "{country} inflation business services index",
                   "exchange rate EUR USD average {year}"],
        "sources": ["central banks", "national statistics offices",
                    "tax authority guidance", "OECD"],
        "example": '[{"label": "telecom levy", "value": 2.5, "unit": "percent", '
                   '"country": "FR", "as_of": "2025"}]',
    },
}
