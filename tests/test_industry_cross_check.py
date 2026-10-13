"""Comparing the taxonomy code against what the resolver called the sector.

`case.industry` is a code and drives archetype_bandwidth,
archetype_resilience and the estate shape. It arrives from the spec or an
analyst, and the only check on it was membership: is this *a* code. Never
whether it is *this entity's* code.

So UNFI ran seventeen research calls and a full estimate as WAREHOUSING -
third-party storage - when it is a wholesale grocery distributor. The two
share an estate shape, so nothing downstream differed; they disagree on the
archetype that *is* the estate, at 100 Mbps against 1,000.

The resolving agent had already written "Grocery and Food Wholesale
Distribution" onto entity_candidate.industry. Nothing carried it to the
case, so nothing could disagree with the code.
"""
import pytest

from app.domain import bics


# The six strings the resolver actually returned, against the codes their
# specs declared. Five agree; the sixth is the one that was wrong.
REAL = [
    ("DRUG_RETAIL", "Retail pharmacy / health & beauty", True),
    ("RETAIL_BANKING", "Offices of Bank Holding Companies", True),
    ("SPECIALTY_RETAIL", "Specialty Retail - Perfumery, Beauty", True),
    ("SPECIALTY_RETAIL", "Retail - Women's Clothing Stores", True),
    ("PARCEL_LOGISTICS", "Package Delivery & Logistics", True),
    ("WAREHOUSING", "Grocery and Food Wholesale Distribution", False),
]


@pytest.mark.parametrize("code,text,expected", REAL)
def test_the_six_companies_that_found_this(code, text, expected):
    assert bics.industry_text_agrees(code, text) is expected


def test_it_separates_the_one_that_was_wrong_from_the_five_that_were_right():
    """Stated as a whole, because a check that flags everything is as
    useless as one that flags nothing."""
    verdicts = [bics.industry_text_agrees(c, t) for c, t, _ in REAL]
    assert verdicts.count(True) == 5 and verdicts.count(False) == 1


# ------------------------------------------------------------- mechanics

def test_a_code_matches_prose_on_a_stem():
    """The resolver writes prose and the taxonomy writes codes. Without
    stemming, RETAIL_BANKING never matches "Bank Holding Companies"."""
    assert bics.industry_text_agrees("RETAIL_BANKING", "Bank Holding") is True
    assert bics.industry_text_agrees("GOLD_MINING", "Gold mine operator") is True


def test_underscores_in_a_code_are_word_breaks():
    assert bics.industry_text_agrees("INTEGRATED_OIL_GAS",
                                     "Integrated oil and gas major") is True


def test_a_shared_filler_word_is_not_agreement():
    """"Services", "Group" and "International" appear in half the taxonomy.
    Matching on one would make the check pass for everything, so they carry
    no weight and the real tokens have to disagree on their own."""
    assert bics.industry_text_agrees(
        "FOOD_MANUFACTURING", "Industrial Services Group") is False
    assert bics.industry_text_agrees(
        "DIVERSIFIED_MINING", "Global Retail Holdings") is False


def test_a_description_of_nothing_but_filler_compares_to_nothing():
    """None, not False. "International Services Group" says nothing about a
    sector, and calling that a disagreement would be a false alarm - which
    is how a reporting check gets ignored."""
    assert bics.industry_text_agrees(
        "FOOD_MANUFACTURING", "International Services Group") is None


def test_retail_is_not_a_filler_word():
    """It distinguishes sectors, unlike "services". Dropping it would make
    DRUG_RETAIL disagree with "Retail pharmacy" - a false alarm, which is
    how a reporting check gets ignored."""
    assert bics.industry_text_agrees("DRUG_RETAIL", "Retail pharmacy") is True


@pytest.mark.parametrize("code,text", [
    (None, "Grocery Wholesale"), ("WAREHOUSING", None),
    ("WAREHOUSING", ""), ("", "Grocery"), ("WAREHOUSING", "   "),
])
def test_nothing_to_compare_is_not_a_disagreement(code, text):
    """None, not False. A missing description is silence, and reporting it
    as a conflict would train a reader to ignore the field."""
    assert bics.industry_text_agrees(code, text) is None


def test_a_code_of_only_filler_words_compares_to_nothing():
    assert bics.industry_text_agrees("GENERAL", "Grocery Wholesale") is None


def test_the_comparison_is_case_insensitive():
    assert bics.industry_text_agrees("drug_retail", "RETAIL PHARMACY") is True


# ------------------------------------------------- it reports, never decides

def test_the_check_returns_a_verdict_and_changes_nothing():
    """Free text cannot settle a taxonomy. The code drives bandwidth,
    resilience and the estate shape, and silently re-labelling a case would
    be worse than the gap this closes - so this is a predicate with no side
    effect, and the caller only logs."""
    before = dict(bics.SHAPE_OF_BICS)
    bics.industry_text_agrees("WAREHOUSING",
                              "Grocery and Food Wholesale Distribution")
    assert bics.SHAPE_OF_BICS == before


def test_the_case_carries_the_resolved_description():
    """The column that makes the comparison possible at all."""
    from app import db
    assert "industry_as_resolved" in [c.name for c in db.case.c]


def test_confirming_an_entity_writes_it():
    """Seven fields were copied onto the case and not this one, which is
    why a mislabelled industry survived a full run."""
    import inspect

    from app.domain import entity_resolution
    src = inspect.getsource(entity_resolution.confirm)
    assert "industry_as_resolved=cand.industry" in src, (
        "confirm() must carry the resolver's sector description onto the "
        "case, or nothing can compare it to the code")


# ------------------------------------- measured against the whole set

def test_a_prefix_match_bridges_two_vocabularies():
    """RAILWAYS stems to "railway" and the resolver wrote "Rail transport".
    No whole token is shared and they plainly agree, so suffix stemming
    alone reported Deutsche Bahn as a conflict."""
    assert bics.industry_text_agrees(
        "RAILWAYS", "Rail transport - operating management holding") is True


def test_a_short_shared_prefix_is_not_agreement():
    """Four characters, because three starts matching things that merely
    begin alike."""
    assert bics.industry_text_agrees("CAR_DEALERSHIPS", "Cargo handling") \
        is False


def test_the_known_false_alarm_is_recorded_not_fixed():
    """Unilever. HOUSEHOLD_PERSONAL_CARE against "Consumer Goods -
    Fast-Moving Consumer Goods (FMCG)" share no token and no prefix, and
    they mean the same thing. These are synonyms in two vocabularies and no
    token heuristic bridges them.

    Asserted as-is rather than special-cased. The check reports for a
    person to read, and one false alarm in twenty-seven comparable cases is
    the price of catching the one that mattered - a reader glances and
    moves on. Papering over it with a synonym list would make the next gap
    invisible instead of visible.
    """
    assert bics.industry_text_agrees(
        "HOUSEHOLD_PERSONAL_CARE",
        "Consumer Goods - Fast-Moving Consumer Goods (FMCG)") is False
