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
import time
import urllib.parse
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".release-work"
APP_URL = (
    "https://lineage-detective.equinoxaifinance.workers.dev/"
    "?receipt=private-invitation-final"
)
PROTECTED_JUDGE_CODE = ROOT / ".judge-access.dpapi"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

SANDBOX = OUT / "v43-sandbox-receipt.json"
IMPLEMENTATION = OUT / "v43-implementation-receipt.json"
HANDOFF = OUT / "v43-human-handoff.zip"
RESULT = OUT / "v43-public-workflow-receipt.json"
DIAGNOSTIC = OUT / "v43-public-workflow-diagnostic.txt"
DIAGNOSTIC_SCREENSHOT = OUT / "v43-public-workflow-diagnostic.png"
TIMELINE = OUT / "v43-public-workflow-timeline.jsonl"


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
    for artifact in (
        SANDBOX,
        IMPLEMENTATION,
        HANDOFF,
        RESULT,
        DIAGNOSTIC,
        DIAGNOSTIC_SCREENSHOT,
        TIMELINE,
    ):
        artifact.unlink(missing_ok=True)
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
            run_button = page.get_by_role(
                "button", name="Approve & run full verified workflow", exact=True
            )
            if not run_button.is_disabled():
                raise RuntimeError("Public workflow was enabled without verified judge access.")

            invitation_url = (
                f"{APP_URL}&judge={urllib.parse.quote(code, safe='')}"
            )
            page.goto(
                invitation_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            code = ""
            invitation_url = ""
            page.get_by_text("Lineage Detective", exact=True).first.wait_for(
                state="visible", timeout=180_000
            )
            page.get_by_text(
                "Model-backed judge gateway verified.", exact=False
            ).wait_for(state="visible", timeout=30_000)
            if "judge=" in page.url:
                raise RuntimeError("Private invitation remained in the browser address bar.")
            run_button = page.get_by_role(
                "button", name="Approve & run full verified workflow", exact=True
            )
            try:
                run_button.wait_for(state="visible", timeout=30_000)
                page.wait_for_function(
                    """
                    () => {
                      const buttons = [...document.querySelectorAll("button")];
                      const run = buttons.find(
                        (button) => button.textContent.trim() ===
                          "Approve & run full verified workflow"
                      );
                      return Boolean(run && !run.disabled);
                    }
                    """,
                    timeout=90_000,
                )
            except Exception:
                body_text = page.locator("body").inner_text(timeout=15_000)
                DIAGNOSTIC.write_text(body_text, encoding="utf-8")
                page.screenshot(path=str(DIAGNOSTIC_SCREENSHOT), full_page=True)
                raise RuntimeError(
                    "Public workflow did not unlock after the private invitation."
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

            # Changing the Streamlit slider causes a script rerun. Re-resolve the
            # primary action after that rerun and prove the click was accepted
            # before starting the workflow deadline.
            page.wait_for_timeout(1_500)
            run_button = page.get_by_role(
                "button", name="Approve & run full verified workflow", exact=True
            )
            run_button.wait_for(state="visible", timeout=30_000)
            page.wait_for_function(
                """
                () => {
                  const button = [...document.querySelectorAll("button")].find(
                    (candidate) => candidate.textContent.trim() ===
                      "Approve & run full verified workflow"
                  );
                  return Boolean(button && !button.disabled);
                }
                """,
                timeout=30_000,
            )
            run_button.click()
            try:
                page.get_by_role(
                    "button", name="Cancel current run", exact=True
                ).wait_for(state="visible", timeout=30_000)
            except Exception:
                body_text = page.locator("body").inner_text(timeout=15_000)
                DIAGNOSTIC.write_text(body_text, encoding="utf-8")
                page.screenshot(path=str(DIAGNOSTIC_SCREENSHOT), full_page=True)
                raise RuntimeError(
                    "Public workflow click was not accepted after the slider rerun."
                )
            progress = page.locator('[aria-label="Verified workflow progress"]')
            deadline = time.monotonic() + 420
            run_started_at = time.monotonic()
            previous_snapshot = None
            idle_since = None
            body_text = ""
            while time.monotonic() < deadline:
                body_text = page.locator("body").inner_text(timeout=15_000)
                progress_text = (
                    progress.inner_text(timeout=15_000)
                    if progress.count()
                    else ""
                )
                snapshot = {
                    "elapsed_seconds": round(time.monotonic() - run_started_at, 3),
                    "progress": progress_text,
                    "approve_button": page.get_by_role(
                        "button",
                        name="Approve & run full verified workflow",
                        exact=True,
                    ).count(),
                    "cancel_button": page.get_by_role(
                        "button", name="Cancel current run", exact=True
                    ).count(),
                    "access_verified": "Model-backed judge gateway verified." in body_text,
                    "failure_visible": any(
                        marker in body_text
                        for marker in (
                            "Investigation failed:",
                            "Workflow failed:",
                            "Sandbox trial failed:",
                            "The autonomous workflow stopped before completion.",
                        )
                    ),
                }
                if snapshot != previous_snapshot:
                    with TIMELINE.open("a", encoding="utf-8") as timeline:
                        timeline.write(json.dumps(snapshot, sort_keys=True) + "\n")
                    previous_snapshot = snapshot
                if (
                    "100%" in progress_text
                    and "2 downstream assets; 2 tag writes confirmed" in body_text
                    and "Download verified human handoff packet (.zip)" in body_text
                ):
                    break
                if (
                    "Investigation failed:" in body_text
                    or "Workflow failed:" in body_text
                    or "Sandbox trial failed:" in body_text
                ):
                    DIAGNOSTIC.write_text(body_text, encoding="utf-8")
                    page.screenshot(path=str(DIAGNOSTIC_SCREENSHOT), full_page=True)
                    raise RuntimeError("Public workflow exposed a visible failure state.")
                if (
                    "Judge code entered. Click Verify judge access" in body_text
                    or "Model-backed judge gateway verified." not in body_text
                ):
                    DIAGNOSTIC.write_text(body_text, encoding="utf-8")
                    page.screenshot(path=str(DIAGNOSTIC_SCREENSHOT), full_page=True)
                    raise RuntimeError(
                        "Public workflow session restarted and lost judge authorization."
                    )
                if (
                    snapshot["elapsed_seconds"] > 20
                    and snapshot["approve_button"] == 1
                    and snapshot["cancel_button"] == 0
                    and "100%" not in progress_text
                ):
                    if idle_since is None:
                        idle_since = time.monotonic()
                    elif time.monotonic() - idle_since > 15:
                        DIAGNOSTIC.write_text(body_text, encoding="utf-8")
                        page.screenshot(path=str(DIAGNOSTIC_SCREENSHOT), full_page=True)
                        raise RuntimeError(
                            "Public workflow returned to idle without a terminal result."
                        )
                else:
                    idle_since = None
                time.sleep(2)
            else:
                DIAGNOSTIC.write_text(body_text, encoding="utf-8")
                page.screenshot(path=str(DIAGNOSTIC_SCREENSHOT), full_page=True)
                raise RuntimeError("Public workflow did not complete within 420 seconds.")
            page.get_by_text(
                "Traced 7 entities through live DataHub lineage.", exact=True
            ).wait_for(state="visible", timeout=15_000)

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
        "public_run_disabled_without_access": True,
        "private_invitation_verified": True,
        "private_invitation_removed_from_url": True,
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
        "schema": "lineage-detective-public-workflow.v43",
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
