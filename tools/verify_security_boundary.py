"""Verify the narrow PYSEC-2026-3447 boundary without hiding the advisory.

This is a repository-shape check, not a vulnerability scanner and not proof that
an old dependency is universally safe. It proves only that this project does not
carry the macOS source-distribution inputs required by the advisory's path.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING_INPUTS = ("pyproject.toml", "setup.py", "setup.cfg", "MANIFEST.in")
RUNTIME_REQUIREMENTS = {"pip==26.1.2", "mcp==1.28.1", "setuptools==83.0.0"}
SIDECAR_REQUIREMENTS = {
    "acryl-datahub==1.6.0.15",
    "mcp-server-datahub==0.6.0",
    "pip==26.1.2",
    "setuptools==81.0.0",
}
LOCKS = {
    "runtime-lock": ("requirements-runtime.lock", "setuptools==83.0.0", "pip==26.1.2"),
    "sidecar-lock": ("requirements-datahub-sidecar.lock", "setuptools==81.0.0", "pip==26.1.2"),
    "sidecar-linux-lock": (
        "requirements-datahub-sidecar-linux.lock",
        "setuptools==81.0.0",
        "pip==26.1.2",
    ),
}


def main() -> int:
    present = [name for name in PACKAGING_INPUTS if (ROOT / name).exists()]
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    sidecar_requirements = (ROOT / "requirements-datahub-sidecar.txt").read_text(encoding="utf-8")
    missing = sorted(
        [f"runtime:{item}" for item in RUNTIME_REQUIREMENTS if item not in requirements]
        + [f"sidecar:{item}" for item in SIDECAR_REQUIREMENTS if item not in sidecar_requirements]
    )
    lock_errors: list[str] = []
    for label, (filename, *expected_pins) in LOCKS.items():
        path = ROOT / filename
        if not path.is_file():
            lock_errors.append(f"{label}:missing")
            continue
        content = path.read_text(encoding="utf-8")
        if "--hash=sha256:" not in content:
            lock_errors.append(f"{label}:hashes-missing")
        lock_errors.extend(f"{label}:missing-{pin}" for pin in expected_pins if pin not in content)
    print("SECURITY BOUNDARY CHECK")
    print(f"repository={ROOT}")
    print(f"packaging_inputs_present={present or 'none'}")
    print(f"required_pins_missing={missing or 'none'}")
    print(f"hash_lock_errors={lock_errors or 'none'}")
    print("runtime_setuptools=83.0.0")
    print("sidecar_advisory_status=UPSTREAM_COMPATIBILITY_BLOCKED_NOT_FIXED")
    if present or missing or lock_errors:
        print("RESULT=FAIL: review SECURITY.md and the affected repository inputs.")
        return 1
    print("RESULT=PASS: runtime is on fixed setuptools; isolated sidecar advisory remains disclosed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
