"""Record a genuine end-to-end Lineage Detective judge run.

This media-only tool drives the already-running application in a disposable
Chrome profile and records the dedicated browser window. It waits on real UI
states instead of cutting around fixed delays, and it exercises the complete
judge path:

investigate -> DataHub write/readback -> review -> sandbox -> apply -> restore
-> downloadable handoff.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = ROOT / "vid" / "judge-final"
RAW_VIDEO = VIDEO_DIR / "lineage-detective-live-raw.mp4"
TIMELINE = VIDEO_DIR / "lineage-detective-live-timeline.json"
FFMPEG_LOG = VIDEO_DIR / "ffmpeg-live-capture.log"
DEMO_MODEL = VIDEO_DIR / "demo-workspace" / "stg_customers.sql"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
APP_URL = "http://127.0.0.1:8503/"

BROKEN_SQL = """-- CRM export v2 renamed the populated field, but this model still reads the legacy column.
select
    customer_id,
    full_name,
    email as email,
    created_at
from {{ ref('raw_customers') }}
"""


def _wait_and_mark(page: Page, text: str, timeline: list[dict], started: float, *, timeout: int) -> None:
    page.get_by_text(text, exact=True).wait_for(state="visible", timeout=timeout)
    timeline.append({"event": text, "seconds": round(time.monotonic() - started, 3)})


def _linger(seconds: float) -> None:
    time.sleep(seconds)


def _scroll_to(page: Page, text: str, timeline: list[dict], started: float, *, pause: float = 3.0) -> None:
    target = page.get_by_text(text, exact=True)
    target.scroll_into_view_if_needed()
    timeline.append({"event": f"show:{text}", "seconds": round(time.monotonic() - started, 3)})
    _linger(pause)


def _stop_capture(capture: subprocess.Popen[bytes]) -> None:
    if capture.poll() is not None:
        return
    assert capture.stdin is not None
    capture.stdin.write(b"q\n")
    capture.stdin.flush()
    try:
        capture.wait(timeout=20)
    except subprocess.TimeoutExpired:
        capture.terminate()
        capture.wait(timeout=10)


def main() -> None:
    if not CHROME.is_file():
        raise SystemExit("Chrome was not found at the expected executable path.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required for the live recording.")

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    DEMO_MODEL.parent.mkdir(parents=True, exist_ok=True)
    DEMO_MODEL.write_text(BROKEN_SQL, encoding="utf-8", newline="\n")
    for backup in DEMO_MODEL.parent.glob(f".{DEMO_MODEL.name}.lineage-detective-*.bak"):
        backup.unlink()

    timeline: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="lineage-detective-judge-video-") as profile:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                profile,
                executable_path=str(CHROME),
                headless=False,
                viewport={"width": 1600, "height": 900},
                args=[
                    "--window-position=0,0",
                    "--window-size=1600,900",
                    "--force-device-scale-factor=1",
                    "--disable-gpu",
                    "--test-type",
                    "--no-first-run",
                ],
            )
            page = context.pages[0]
            page.goto(APP_URL, wait_until="domcontentloaded", timeout=30_000)
            investigate = page.get_by_role(
                "button", name="Investigate, contain & draft rewrite", exact=True
            )
            investigate.wait_for(state="visible", timeout=30_000)

            # Keep the first frame honest: the real app, its DataHub endpoint, and its
            # model-backed status are visible before the sidebar is collapsed.
            _linger(2.5)
            with FFMPEG_LOG.open("wb") as ffmpeg_log:
                capture = subprocess.Popen(
                    [
                        ffmpeg,
                        "-y",
                        "-f",
                        "gdigrab",
                        "-draw_mouse",
                        "1",
                        "-framerate",
                        "30",
                        "-i",
                        "title=Lineage Detective - Google Chrome",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "18",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        str(RAW_VIDEO),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=ffmpeg_log,
                )
                started = time.monotonic()
                timeline.append({"event": "capture_started", "seconds": 0.0})
                try:
                    _linger(6)
                    collapse = page.locator('[data-testid="stSidebarCollapseButton"]')
                    if collapse.count() == 1 and collapse.is_visible():
                        collapse.click()
                        timeline.append(
                            {"event": "sidebar_collapsed", "seconds": round(time.monotonic() - started, 3)}
                        )
                        _linger(2)

                    investigate.hover()
                    _linger(1)
                    investigate.click()
                    timeline.append(
                        {"event": "investigate_clicked", "seconds": round(time.monotonic() - started, 3)}
                    )

                    _wait_and_mark(
                        page,
                        "2 · Review the proposed rewrite",
                        timeline,
                        started,
                        timeout=90_000,
                    )
                    _scroll_to(page, "Lineage the agent walked", timeline, started, pause=4)
                    _scroll_to(page, "Diagnosis", timeline, started, pause=5)
                    _scroll_to(page, "2 · Review the proposed rewrite", timeline, started, pause=4)
                    _scroll_to(page, "Exact diff", timeline, started, pause=7)

                    sandbox = page.get_by_role(
                        "button", name="Approve this rewrite & run the sandbox", exact=True
                    )
                    sandbox.hover()
                    _linger(1)
                    sandbox.click()
                    timeline.append(
                        {"event": "sandbox_clicked", "seconds": round(time.monotonic() - started, 3)}
                    )
                    # The sandbox callback updates the primary detective panel near the top of
                    # the app. Move there immediately so the judge sees real reset/seed/build/
                    # verify/rollback phases instead of staring at the already-reviewed diff.
                    live_status = page.locator('[aria-label="Lineage Detective status"]')
                    if live_status.count() == 1:
                        live_status.scroll_into_view_if_needed()
                        timeline.append(
                            {
                                "event": "show:live_sandbox_status",
                                "seconds": round(time.monotonic() - started, 3),
                            }
                        )

                    _wait_and_mark(
                        page,
                        "4 · Choose what happens next",
                        timeline,
                        started,
                        timeout=75_000,
                    )
                    _scroll_to(page, "3 · Sandbox verification receipt", timeline, started, pause=6)
                    _scroll_to(page, "4 · Choose what happens next", timeline, started, pause=3)

                    target = page.get_by_role(
                        "textbox", name="Checked-out dbt model file to update", exact=True
                    )
                    target.fill(str(DEMO_MODEL.relative_to(ROOT)))
                    target.press("Tab")
                    timeline.append(
                        {"event": "target_selected", "seconds": round(time.monotonic() - started, 3)}
                    )
                    _linger(2)
                    apply_button = page.get_by_role(
                        "button", name="Apply verified rewrite to this file", exact=True
                    )
                    expect(apply_button).to_be_enabled(timeout=15_000)
                    apply_button.hover()
                    _linger(1)
                    apply_button.click()
                    _wait_and_mark(
                        page,
                        (
                            "Verified rewrite applied to the selected file. The post-write hash matches "
                            "the sandbox-approved proposal and a sibling backup is available."
                        ),
                        timeline,
                        started,
                        timeout=20_000,
                    )
                    _linger(5)

                    restore = page.get_by_role(
                        "button", name="Restore the verified backup", exact=True
                    )
                    restore.hover()
                    _linger(1)
                    restore.click()
                    _wait_and_mark(
                        page,
                        "Backup restored and its original hash was verified.",
                        timeline,
                        started,
                        timeout=20_000,
                    )
                    _linger(4)

                    handoff = page.get_by_role(
                        "button", name="Prepare downloadable handoff", exact=True
                    )
                    handoff.hover()
                    _linger(1)
                    handoff.click()
                    _wait_and_mark(
                        page,
                        "4 · Verified human handoff",
                        timeline,
                        started,
                        timeout=20_000,
                    )
                    _scroll_to(page, "4 · Verified human handoff", timeline, started, pause=12)
                    timeline.append(
                        {"event": "capture_complete", "seconds": round(time.monotonic() - started, 3)}
                    )
                finally:
                    _stop_capture(capture)
                    context.close()

    TIMELINE.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    if not RAW_VIDEO.is_file() or RAW_VIDEO.stat().st_size < 1_000_000:
        raise SystemExit(f"The live capture was not produced. Inspect {FFMPEG_LOG}.")
    if DEMO_MODEL.read_text(encoding="utf-8") != BROKEN_SQL:
        raise SystemExit("The video demo model was not restored to its original bytes.")
    if list(DEMO_MODEL.parent.glob(f".{DEMO_MODEL.name}.lineage-detective-*.bak")):
        raise SystemExit("A recording backup was unexpectedly left behind.")
    print(RAW_VIDEO)
    print(TIMELINE)


if __name__ == "__main__":
    main()
