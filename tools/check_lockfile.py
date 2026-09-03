#!/usr/bin/env python3
"""Are the builds reproducible?

Audit finding A-09. Direct dependencies are pinned - 12 of 12, all `==` - and
there is no lock file, so every transitive version floats between builds. An
external auditor observed exactly that skew: 113 pytest failures under Python
3.13 against a repo pinned to 3.12, with no way to tell which failures were
defects and which were the environment.

Pinning `fastapi==0.115.6` says nothing about which `starlette`, `anyio` or
`typing-extensions` came with it. Those are the versions that actually run.

This checks the lock exists and matches. It cannot create one: a lock is a
record of what a resolver actually installed, and inventing transitive versions
would produce a file that looks authoritative and is fiction.

    make lock          produce the lock files, in the built containers
    make check-lock    verify they exist and agree with requirements.txt

Exit codes:
    0  every requirements file has a lock, and the pins agree
    1  a lock is missing, or a direct pin disagrees with its lock
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (requirements file, lock file, the compose service that can produce it)
PAIRS = [
    ("api_service/requirements.txt", "api_service/requirements.lock", "api"),
    ("analyst_ui/requirements.txt", "analyst_ui/requirements.lock", "ui"),
]


def _pins(text: str) -> dict:
    """{package: version} from a requirements or freeze file.

    Extras are dropped from the name - `uvicorn[standard]==0.34.0` locks as
    `uvicorn==0.34.0` - because pip freeze reports the distribution, not the
    extras that selected it. Comparing them literally would report a false
    mismatch on a correct lock.
    """
    pins = {}
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"([A-Za-z0-9._-]+)(?:\[[^\]]*\])?==([^\s;]+)", line)
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def _base_images() -> list:
    """Is the runtime itself pinned?

    `FROM python:3.12-slim` is a moving tag: 3.12.1 and 3.12.9 are both it, and
    a rebuild months apart gets different interpreters. An external auditor's
    skew came from running under 3.13 against a repo that believed it was
    3.12 - and the tag could not have told them otherwise.
    """
    problems = []
    for dockerfile in sorted(ROOT.rglob("Dockerfile")):
        for line in dockerfile.read_text().splitlines():
            if not line.startswith("FROM "):
                continue
            image = line.split()[1]
            if "@sha256:" in image:
                continue
            tag = image.split(":")[-1] if ":" in image else "latest"
            # A patch-level tag still moves, but far less. A digest is the only
            # thing that does not.
            if tag.count(".") < 2:
                problems.append(
                    f"{dockerfile.relative_to(ROOT)} uses {image} - a moving "
                    f"tag. Pin the patch level, or a digest for a build that "
                    f"cannot drift at all")
    return problems


def main() -> int:
    problems, notes = [], []
    problems.extend(_base_images())

    for req_path, lock_path, service in PAIRS:
        req, lock = ROOT / req_path, ROOT / lock_path
        if not req.exists():
            problems.append(f"{req_path} does not exist")
            continue

        declared = _pins(req.read_text())
        if not lock.exists():
            problems.append(
                f"{lock_path} is missing - {len(declared)} direct pin(s) and "
                f"no record of the transitive versions that ran. Produce it "
                f"with:  docker compose run --rm {service} pip freeze > "
                f"{lock_path}")
            continue

        locked = _pins(lock.read_text())
        notes.append(f"{lock_path}: {len(locked)} package(s) locked, "
                     f"{len(declared)} declared directly")

        for name, version in sorted(declared.items()):
            if name not in locked:
                problems.append(
                    f"{lock_path} does not contain {name}, which "
                    f"{req_path} pins at {version}")
            elif locked[name] != version:
                problems.append(
                    f"{name}: {req_path} pins {version}, {lock_path} has "
                    f"{locked[name]} - the lock and the requirement disagree, "
                    f"so neither describes the build")

        # A lock with no more packages than the requirements file is a copy,
        # not a lock: the transitive closure of fastapi alone is a dozen
        # packages.
        if len(locked) <= len(declared):
            problems.append(
                f"{lock_path} has {len(locked)} package(s) for {len(declared)} "
                f"direct requirement(s) - a lock records the transitive "
                f"closure, so this looks like a copy of requirements.txt "
                f"rather than a freeze")

    for note in notes:
        print(f"  {note}")
    print()
    if problems:
        print(f"{len(problems)} reproducibility problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        print()
        print("Until a lock exists, a failure observed in one environment "
              "cannot be attributed to the code rather than the environment.")
        return 1
    print("Both requirements files have a lock and the direct pins agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
