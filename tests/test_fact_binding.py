"""A fact that cannot count what its class says.

"80 countries with active presence" was registered as a Location footprint and
became 80 sites to allocate, then landed as a single GB row because that is
what a single-row total does.

A guard already existed for this class - added after "460,000,000 EUR per year"
became 460 million sites - and it rejects money, users and bandwidth. It did
not reject countries, because a count of countries is a count. The value was
plausible too: AstraZeneca is in roughly 100 countries and has roughly 100
sites, so a unit error between two counts is invisible in the figure.

Its own file, loading the two checks from source rather than importing
known_facts, which imports sqlalchemy and blocks its file wherever that is not
installed. Fifth time this session a guard was written somewhere it could not
run.
"""
import types
from pathlib import Path


def _checks():
    """The two check functions, without importing the module around them."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    source = (app / "domain" / "known_facts.py").read_text()
    namespace = {}
    exec(source[source.index("BINDABLE = {"):
                source.index("def value_implausible_for_class")], namespace)
    exec(source[source.index("# What a subject is counting"):
                source.index("# Corroboration outcome")], namespace)
    return types.SimpleNamespace(**namespace)


known_facts = _checks()


def test_a_count_of_something_else_is_refused_as_a_site_count():
    """"80 countries with active presence" was registered as a Location
    footprint and became 80 sites to allocate.

    A guard already existed for this class - it was added after a cost line of
    "460,000,000 EUR per year" became 460 million sites - and it rejects money,
    users and bandwidth. It did not reject countries, because a count of
    countries is a count. And the value was plausible too: AstraZeneca is in
    roughly 100 countries and has roughly 100 sites, so a unit error between
    two counts is invisible in the figure."""
    for unit in ("countries", "markets", "territories", "subsidiaries",
                 "brands", "patients"):
        assert known_facts.unit_conflicts_with_class("Location footprint",
                                                     unit)
    for unit in ("sites", "locations", "facilities", ""):
        assert not known_facts.unit_conflicts_with_class("Location footprint",
                                                         unit)


def test_the_subject_is_checked_because_the_unit_is_usually_blank():
    """The unit check only fires if the unit says "countries". The signal here
    was in the subject the agent wrote, and the unit was almost certainly
    empty."""
    refused = ("countries with active presence", "markets served",
               "employees worldwide", "legal entities")
    for subject in refused:
        assert known_facts.subject_conflicts_with_class(
            "Location footprint", subject), subject

    accepted = ("manufacturing sites", "distribution centres", "offices",
                "sites")
    for subject in accepted:
        assert not known_facts.subject_conflicts_with_class(
            "Location footprint", subject), subject


def test_an_existing_bad_binding_is_flagged_not_deleted():
    """The checks did not exist when the fact was stored. It was asserted in
    good faith, an estimate may have been run on it, and unbinding it silently
    would change a number nobody was told about."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "migrations.py").exists())
    migrations = (app / "migrations.py").read_text()
    block = migrations[migrations.index("def _migrate_v61"):][:2200]

    assert "update(db.known_fact)" in block, "the migration must flag"
    assert "delete(" not in block, "it must not delete"
    assert "binding_conflict_found_at" in block, (
        "the analyst needs to know when the model started refusing it")


def test_the_flag_actually_stops_the_binding():
    """A column nobody reads is the defect this whole session keeps finding."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    footprint = (app / "domain" / "footprint.py").read_text()
    start = footprint.index("def _rejected(row)")
    block = footprint[start:start + 1600]
    assert "binding_conflict" in block
    assert block.index("binding_conflict") < block.index(
        "unit_conflicts_with_class")


# ------------------- an agent that elaborates the class it was asked for
def test_the_class_is_the_one_requested_not_the_one_returned():
    """The sweep runs one call per fact class, so the class is already known.

    The agent elaborated it: "Operating-model cost" came back as
    "Operating-model cost - Selling, general and administrative expense",
    66 characters into a 64-character column, and the insert failed with a
    Postgres truncation error the analyst had no way to read.

    Width was the symptom. An invented class breaks the register:
    corroboration and the prefill dedupe both match on (fact_class, subject),
    and the analyst cannot select that class by hand - so the fact could never
    meet another about the same thing."""
    source = (_app_domain() / "known_facts.py").read_text()
    block = source[source.index('for i, fact in enumerate('):][:2000]
    assert 'fact = {**fact, "fact_class": fact_class}' in block, (
        "the requested class must override the returned one")
    assert "class_as_returned" in block, (
        "what the agent said must be recorded, not silently dropped")


def test_the_elaboration_is_kept_as_a_note():
    """"Selling, general and administrative expense" is real information about
    the figure. Losing it is worse than keeping it - it just belongs in the
    note, where it describes the number rather than naming its class."""
    source = (_app_domain() / "known_facts.py").read_text()
    block = source[source.index('for i, fact in enumerate('):][:2000]
    assert 'fact["note"]' in block
    for separator in (" - ", ": "):
        assert repr(separator) in block or separator in block


def test_an_over_long_field_is_refused_readably():
    """StringDataRightTruncation is a wall of SQL and bound parameters that
    tells an analyst nothing about what to change."""
    import ast

    # The whole function, not a guessed window. A 2,600-character slice
    # reached the length check and stopped short of the insert 4,402
    # characters in, so the ordering assertion had nothing to compare.
    source = (_app_domain() / "known_facts.py").read_text()
    register = next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.FunctionDef) and n.name == "register")
    block = ast.unparse(register)

    assert "too_long" in block
    assert "characters and the register allows" in block
    assert block.index("too_long") < block.index("insert("), (
        "the length must be refused before the row is written")


def _app_domain():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())
    return app / "domain"
