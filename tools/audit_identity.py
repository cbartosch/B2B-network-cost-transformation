#!/usr/bin/env python3
"""Section A of the audit mandate: what exactly is being audited.

Written as a file rather than a shell one-liner because the patterns need
quotes the shell keeps eating, and an audit that cannot state the commit it
examined is not an audit.
"""
import pathlib
import re
import subprocess
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "api_service" / "app"


def _git(args: str) -> str:
    return subprocess.run(f"git {args}", shell=True, capture_output=True,
                          text=True, cwd=ROOT).stdout.strip()


def _find(pattern: str, source: str, label: str) -> str:
    match = re.search(pattern, source)
    return match.group(1) if match else f"<{label} not found>"


def main() -> int:
    config = (APP / "config.py").read_text()
    migrations = (APP / "migrations.py").read_text()
    api = (APP / "routers" / "api.py").read_text()
    prompts = (APP / "llm" / "prompts.py").read_text()

    print("IDENTITY")
    print(f"  branch                 {_git('rev-parse --abbrev-ref HEAD')}")
    print(f"  commit                 {_git('rev-parse --short HEAD')}")
    print(f"  release                {_git('log -1 --pretty=%s')}")
    print(f"  schema version         "
          f"{_find(r'SCHEMA_VERSION = (\d+)', migrations, 'schema')}")
    print(f"  calculation version    "
          f"{_find(r'CALCULATION_VERSION = .([^\'\"]+)', config, 'calc')}")
    print(f"  simulation model       "
          f"{_find(r'SIMULATION_MODEL_VERSION = .([^\'\"]+)', config, 'sim')}")

    print("\nSURFACE")
    verbs = re.findall(r'@router\.(get|post|put|delete)\("', api)
    print(f"  routes                 {len(verbs)} {dict(Counter(verbs))}")
    print(f"  migration steps        "
          f"{len(re.findall(r'(\d+): _migrate_v', migrations))}")
    print(f"  registered prompts     "
          f"{len(re.findall(r'prompt_id=', prompts))}")
    models = len(re.findall(r"^class \w+\(BaseModel\):", api, re.M))
    print(f"  request models         {models}")
    pages = sorted(p.name for p in
                   (ROOT / "analyst_ui" / "streamlit_app" / "pages").glob("*.py"))
    print(f"  interface pages        {len(pages)}")

    print("\nCONTROLS")
    print(f"  authentication         "
          f"{'bearer API_TOKEN, optional' if 'API_TOKEN' in config else 'none'}")
    has_roles = bool(re.search(r"\brole\b|RBAC|permission", config, re.I))
    print(f"  authorization          "
          f"{'present' if has_roles else 'NONE - no roles, no per-user scoping'}")
    print(f"  row-level security     "
          f"{'present' if 'row_level' in config.lower() else 'NONE'}")
    print(f"  TLS pinning            "
          f"{'enforced' if 'PIN_ENFORCE' in (APP / 'llm' / 'providers' / '_transport.py').read_text() else 'absent'}")

    print("\nEVIDENCE NOT EXECUTABLE HERE")
    tests = subprocess.run("grep -rh '^def test_' tests/*.py | wc -l",
                           shell=True, capture_output=True, text=True,
                           cwd=ROOT).stdout.strip()
    print(f"  test functions         {tests}, 0 executed in this environment")
    print(f"  live provider calls    0")
    print(f"  database instance      none reachable from the audit sandbox")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
