"""The release this image was built from.

Read from the VERSION file the repository maintains, which the Dockerfile now
copies into the image. It was a hardcoded string "kept in sync by hand" and
drifted to 4.31.0 while VERSION said 4.198.0 - 167 releases, with /v1/health
reporting the old one, so an operator could not tell which release was running.

The file's own comment recorded that this had happened before, at
"4.7.1-scaffold", and asked for the Dockerfile change rather than another
bump. This is that change.

The fallback is deliberately a marker rather than a plausible version: a
missing VERSION file should look obviously wrong, not like a real release.
"""
import pathlib
import re

_FALLBACK = "unknown-no-VERSION-file"


def _read() -> str:
    """The build string from VERSION, or a marker.

    Looks beside the app directory first - where the Dockerfile puts it - then
    at the repository root, which is where it sits when running from a checkout
    rather than an image.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parents[2] / "VERSION",     # /app/VERSION in image
                      here.parents[3] / "VERSION"):    # repo root in checkout
        try:
            text = candidate.read_text()
        except OSError:
            continue
        match = re.search(r"build:\s*([0-9A-Za-z.\-+]+)", text)
        if match:
            return match.group(1)
    return _FALLBACK


BUILD = _read()
