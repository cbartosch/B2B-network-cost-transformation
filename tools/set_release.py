#!/usr/bin/env python3
"""Write the release number everywhere it is declared, from one argument.

Two files carry it: the top-level VERSION, which the repository maintains, and
api_service/app/_version.py, which /v1/health reports. They were kept in sync
by hand and drifted by 167 releases.

Both are literals on purpose. A version computed at import cannot be read by a
static auditor, an SBOM or a diff - so the answer is not to derive one from the
other but to write both from one place, and to fail the build when they
disagree.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
MODULE = ROOT / "api_service" / "app" / "_version.py"
PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")


def read() -> tuple:
    """The release each file declares."""
    version = None
    if VERSION_FILE.exists():
        match = re.search(r"build:\s*([0-9A-Za-z.\-+]+)", VERSION_FILE.read_text())
        version = match.group(1) if match else None
    build = None
    if MODULE.exists():
        match = re.search(r'^BUILD\s*=\s*"([^"]+)"', MODULE.read_text(), re.M)
        build = match.group(1) if match else None
    return version, build


def write(release: str) -> None:
    if not PATTERN.match(release):
        raise SystemExit(
            f"{release!r} is not a release number. Expected 1.2.3, optionally "
            f"with a suffix - a value this script cannot check is one that can "
            f"drift again.")
    text = VERSION_FILE.read_text() if VERSION_FILE.exists() else "build: 0.0.0\n"
    VERSION_FILE.write_text(re.sub(r"build:\s*[0-9A-Za-z.\-+]+",
                                   f"build: {release}", text, count=1))
    module = MODULE.read_text()
    MODULE.write_text(re.sub(r'^BUILD\s*=\s*"[^"]+"', f'BUILD = "{release}"',
                             module, count=1, flags=re.M))
    print(f"VERSION and _version.py both set to {release}")


def check() -> int:
    version, build = read()
    if version is None:
        print("VERSION declares no build")
        return 1
    if build is None:
        print("_version.py declares no BUILD literal - a computed value cannot "
              "be read by a static auditor, an SBOM or a diff")
        return 1
    if version != build:
        print(f"release identity disagrees: VERSION={version} but "
              f"_version.py={build}. /v1/health reports the second, so an "
              f"operator would be told the wrong release.")
        return 1
    print(f"release identity agrees: {version}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--check":
        write(sys.argv[1])
        sys.exit(0)
    sys.exit(check())
