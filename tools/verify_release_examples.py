"""Verify every committed judge example without trusting its manifest."""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repair import verify_sandbox_receipt


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    root = ROOT / "examples" / "generated"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    for case in manifest.get("cases") or []:
        case_root = root / str(case["case"])
        receipt_path = case_root / "sandbox-verification-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        valid, reason = verify_sandbox_receipt(receipt)
        if not valid:
            failures.append(f"{case['case']}: invalid receipt: {reason}")
        for name, expected in (case.get("files") or {}).items():
            path = case_root / name
            if not path.is_file():
                failures.append(f"{case['case']}: missing {name}")
                continue
            if path.stat().st_size != int(expected["bytes"]):
                failures.append(f"{case['case']}: size mismatch for {name}")
            if sha256(path) != expected["sha256"]:
                failures.append(f"{case['case']}: SHA-256 mismatch for {name}")
        archive = case_root / "human-handoff.zip"
        try:
            with zipfile.ZipFile(archive) as package:
                if package.testzip() is not None:
                    failures.append(f"{case['case']}: ZIP CRC failure")
                embedded = json.loads(
                    package.read("sandbox-verification-receipt.json").decode("utf-8")
                )
                if embedded.get("receipt_sha256") != receipt.get("receipt_sha256"):
                    failures.append(f"{case['case']}: ZIP receipt does not match standalone receipt")
                if hashlib.sha256(package.read("proposed-model.sql")).hexdigest() != receipt.get(
                    "proposal_sha256"
                ):
                    failures.append(f"{case['case']}: ZIP model does not match proposal hash")
        except Exception as exc:
            failures.append(f"{case['case']}: ZIP verification error: {type(exc).__name__}: {exc}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Verified {len(manifest['cases'])} example cases and every bound artifact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
