"""Execute the deployed judge workflow and save its real downloadable artifacts.

This is a release-verification tool. It never prints or persists the plaintext
judge access code. The public application and gateway remain the systems under
test; no synthetic catalog or local workflow substitute is used.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".release-work"
APP_URL = (
    "https://lineage-detective.equinoxaifinance.workers.dev/"
    "?receipt=six-hop-final"
)
PROTECTED_JUDGE_CODE = ROOT / ".judge-access.dpapi"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

SANDBOX = OUT / "v41-sandbox-receipt.json"
IMPLEMENTATION = OUT / "v41-implementation-receipt.json"
HANDOFF = OUT / "v41-human-handoff.zip"
RESULT = OUT / "v41-public-workflow-receipt.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def judge_code() -> str:
    script = (
        "$v=(Get-Content -Raw -LiteralPath $env:LINEAGE_PROTECTED_CODE_PATH).Trim();"
        "$s=$v|ConvertTo-SecureString;"
        "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
        "try{[Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))}"
        "finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}"
    )
    value = subprocess.check_output(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", script],
        text=True,
        env={
            **os.environ,
            "LINEAGE_PROTECTED_CODE_PATH": str(PROTECTED_JUDGE_CODE),
        },
    )
    if len(value) < 24:
        raise RuntimeError("Protected judge access did not decrypt.")
    return value


def download(page, button_name: str, destination: Path) -> None:
    with page.expect_download(timeout=15_000) as pending:
        page.get_by_role("button", name=button_name, exact=True).click()
    pending.value.save_as(destination)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    code = judge_code()
    console_errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="lineage-receipt-proof-") as profile:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                profile,
                executable_path=str(CHROME),
                headless=True,
                viewport={"width": 1600, "height": 900},
                args=["--disable-gpu", "--no-first-run", "--test-type"],
            )
            page = context.pages[0]
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text)
                    if message.type == "error"
                    else None
                ),
            )
            page.goto(APP_URL, wait_until="domcontentloaded", timeout=60_000)
            page.get_by_text("Lineage Detective", exact=True).first.wait_for(
                state="visible", timeout=180_000
            )

            slider = (
                page.locator('[data-testid="stSlider"]')
                .filter(has_text="Max upstream hops")
                .first
                .locator('input[type="range"]')
            )
            slider.focus()
            slider.press("End")
            if slider.input_value() != "6":
                raise RuntimeError("Judge workflow did not select six hops.")

            code_input = page.get_by_label(
                "Judge access code (from testing instructions)", exact=True
            )
            code_input.fill(code)
            code_input.press("Enter")
            code = ""
            page.get_by_text(
                "Model-backed judge gateway verified.", exact=False
            ).wait_for(state="visible", timeout=30_000)

            page.get_by_role(
                "button", name="Approve & run full verified workflow", exact=True
            ).click()
            page.get_by_text(
                (
                    "One-click workflow completed this proposal through sandbox "
                    "verification and the selected finish action. Manual controls remain "
                    "available in Advanced settings for a new run."
                ),
                exact=True,
            ).wait_for(state="visible", timeout=180_000)
            page.get_by_text(
                "Traced 7 entities through live DataHub lineage.", exact=True
            ).wait_for(state="visible", timeout=15_000)

            progress = page.locator('[aria-label="Verified workflow progress"]')
            if "100%" not in progress.inner_text():
                raise RuntimeError("Public workflow did not expose a completed progress rail.")
            if "2 downstream assets; 2 tag writes confirmed" not in page.locator(
                "body"
            ).inner_text():
                raise RuntimeError("Containment readback was missing.")

            download(page, "Download JSON receipt", SANDBOX)
            download(page, "Download implementation receipt", IMPLEMENTATION)
            download(
                page,
                "Download verified human handoff packet (.zip)",
                HANDOFF,
            )
            context.close()

    sandbox = json.loads(SANDBOX.read_text(encoding="utf-8"))
    implementation = json.loads(IMPLEMENTATION.read_text(encoding="utf-8"))
    with zipfile.ZipFile(HANDOFF) as archive:
        bad_zip_member = archive.testzip()
        members = sorted(archive.namelist())

    checks = {
        "six_hops_selected": True,
        "seven_entities_visible": True,
        "progress_100_visible": True,
        "containment_readback_visible": True,
        "sandbox_verified": bool(
            sandbox.get("verified")
            and sandbox.get("rollback_verified")
            and sandbox.get("after", {}).get("filled") == 8
            and sandbox.get("after", {}).get("total") == 8
        ),
        "implementation_verified": bool(
            implementation.get("applied")
            and implementation.get("state") == "applied_verified"
            and implementation.get("after_sha256")
            == implementation.get("expected_after_sha256")
            == implementation.get("proposal_sha256")
        ),
        "handoff_zip_valid": bad_zip_member is None and len(members) >= 3,
        "browser_console_errors": console_errors,
    }
    status = "PASS" if all(
        value is True for key, value in checks.items() if key != "browser_console_errors"
    ) and not console_errors else "FAIL"
    result = {
        "schema": "lineage-detective-public-workflow.v41",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "app_url": APP_URL,
        "checks": checks,
        "artifacts": {
            "sandbox": {
                "path": str(SANDBOX),
                "bytes": SANDBOX.stat().st_size,
                "sha256": sha256(SANDBOX),
            },
            "implementation": {
                "path": str(IMPLEMENTATION),
                "bytes": IMPLEMENTATION.stat().st_size,
                "sha256": sha256(IMPLEMENTATION),
            },
            "handoff": {
                "path": str(HANDOFF),
                "bytes": HANDOFF.stat().st_size,
                "sha256": sha256(HANDOFF),
                "members": members,
            },
        },
    }
    RESULT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "result": str(RESULT)}, indent=2))
    raise SystemExit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
