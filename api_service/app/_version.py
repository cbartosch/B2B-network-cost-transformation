"""The release this image was built from.

A literal, written by the release step that also writes VERSION - not a
hardcoded string maintained by hand, and not computed at import.

It was maintained by hand and drifted to 4.31.0 while VERSION said 4.198.0:
167 releases, with /v1/health reporting the old one, so an operator could not
tell which release was running. The file's own comment recorded that this had
happened before at "4.7.1-scaffold" and asked for a real fix.

Computing it from VERSION at import solved the drift and broke something else:
a release number that only exists at runtime cannot be read by a static
auditor, an SBOM, or anyone looking at a diff. So it is a literal again, and
`tools/set_release.py` writes both files from one argument - the sync is
scripted rather than remembered, and `make check-identity` fails the build if
they ever disagree.
"""

BUILD = "4.242.0"
