"""Where the sample driver reads its company spec from.

It read `--out/companies.json`, so the input lived inside the output. That
directory is pulled out of the container before a restart and pushed back
afterwards, which made the spec a function of whichever backup was restored
last. One restore predated CR-02b and six companies ran at a three-commit-old
scope - BASF 219 sites to 101, Siemens 495 to 195, Unilever 214 to 43 - with
every company reporting success and the validation gate passing.
"""
import importlib.util
import json
import pathlib

import pytest


def _driver():
    for root in (pathlib.Path("/app"), pathlib.Path(__file__).resolve().parents[1]):
        f = root / "tools" / "run_samples.py"
        if f.exists():
            spec = importlib.util.spec_from_file_location("_rs_spec", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    pytest.skip("tools/run_samples.py not present")


@pytest.fixture()
def driver():
    return _driver()


def _spec_file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"companies": []}), encoding="utf-8")
    return path


# ------------------------------------------------------- the defect itself

def test_a_spec_inside_the_output_directory_is_refused(driver, tmp_path):
    """Not deprioritised - refused. A fallback that silently reads the wrong
    file is the defect; making it the last resort would only make it rarer,
    and rarer is how this one survived long enough to matter."""
    out = tmp_path / "samples"
    stale = _spec_file(out / "companies.json")
    with pytest.raises(SystemExit) as e:
        driver.resolve_spec(str(stale), out)
    assert "--out" in str(e.value)


def test_a_spec_nested_deeper_inside_the_output_is_also_refused(driver,
                                                                tmp_path):
    out = tmp_path / "samples"
    nested = _spec_file(out / "backup" / "companies.json")
    with pytest.raises(SystemExit):
        driver.resolve_spec(str(nested), out)


def test_an_explicit_spec_outside_the_output_is_accepted(driver, tmp_path):
    out = tmp_path / "samples"
    out.mkdir(parents=True)
    good = _spec_file(tmp_path / "repo" / "companies.json")
    assert driver.resolve_spec(str(good), out) == good.resolve()


def test_a_missing_explicit_spec_fails_loudly(driver, tmp_path):
    with pytest.raises(SystemExit) as e:
        driver.resolve_spec(str(tmp_path / "nope.json"), tmp_path / "out")
    assert "does not exist" in str(e.value)


# ------------------------------------------------------------- the default

def test_the_default_never_consults_the_output_directory(driver, tmp_path):
    """With no --spec, resolution looks at the repository and the image and
    nowhere else. A companies.json sitting in --out must not be found."""
    out = tmp_path / "samples"
    _spec_file(out / "companies.json")
    found = driver.resolve_spec("", out)
    assert found != (out / "companies.json").resolve()
    assert out.resolve() not in found.parents


def test_the_default_resolves_to_the_committed_spec(driver):
    """And it must be the real one, with every company in it - a resolver
    that finds an empty file is no better than the stale one it replaced."""
    found = driver.resolve_spec("", pathlib.Path("/nonexistent-out"))
    doc = json.loads(found.read_text("utf-8"))
    assert len(doc["companies"]) >= 20
    assert {"slug", "declared_footprint"} <= set(doc["companies"][0])


def test_the_spec_identity_is_recorded_for_the_manifest(driver):
    """Every manifest names the spec that produced it. Without it nothing in
    any artifact said which file had been read, which is why the scope
    reversion was invisible until estates moved in unrelated industries."""
    assert set(driver.SPEC_IDENTITY) == {"path", "digest"}


def test_the_spec_does_not_live_in_the_published_output_directory(driver):
    """The other half of the same defect, and the one that bit second.

    Stopping the driver READING from its output directory did not stop
    publishing a run from WRITING over its input: a publish copies the whole
    output directory back into the repository, so a spec sitting inside it is
    replaced by whatever the container happened to hold. The commit that
    fixed the read direction overwrote the committed 174-row spec with the
    stale 97-row one it had just been handed to prove the fix worked.

    Separate directories make it unrepresentable. This asserts they stay
    separate.
    """
    assert "outside_in" not in driver.SPEC_RELATIVE.parts, (
        "the spec must not live under samples/outside_in/ - that directory "
        "is the published output and is copied back over the repository")
