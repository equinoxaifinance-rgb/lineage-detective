"""Record the current one-approval Lineage Detective judge path.

The capture is a real browser window driven against the already-running local
product. It does not splice screenshots or skip the wait states. The recording
starts on the usable application, clicks the same autonomous control a judge
sees, waits for the verified workflow to finish, and then walks the evidence,
diff, sandbox receipt, implementation proof, and downloadable handoff.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = ROOT / "vid" / "judge-final"
RAW_VIDEO = VIDEO_DIR / "lineage-detective-live-raw.mp4"
TIMELINE = VIDEO_DIR / "lineage-detective-live-timeline.json"
FFMPEG_LOG = VIDEO_DIR / "ffmpeg-live-capture.log"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
APP_URL = "http://127.0.0.1:8503/"


def _mark(timeline: list[dict], started: float, event: str) -> None:
    timeline.append({"event": event, "seconds": round(time.monotonic() - started, 3)})


def _show(
    page: Page,
    text: str,
    timeline: list[dict],
    started: float,
    *,
    pause: float,
    timeout: int = 30_000,
) -> None:
    target = page.get_by_text(text, exact=True).first
    target.wait_for(state="visible", timeout=timeout)
    target.scroll_into_view_if_needed()
    _mark(timeline, started, f"show:{text}")
    time.sleep(pause)


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
            approve = page.get_by_role(
                "button", name="Approve & run full verified workflow", exact=True
            )
            approve.wait_for(state="visible", timeout=30_000)
            page.get_by_text("Lineage Detective", exact=True).first.wait_for(
                state="visible", timeout=30_000
            )
            time.sleep(2.5)

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
                _mark(timeline, started, "capture_started")
                try:
                    # Six seconds of the actual app give the opening narration room to
                    # establish authorship and show the live model/DataHub boundary.
                    time.sleep(6)
                    collapse = page.locator('[data-testid="stSidebarCollapseButton"]')
                    if collapse.count() == 1 and collapse.is_visible():
                        collapse.click()
                        _mark(timeline, started, "sidebar_collapsed")
                        time.sleep(1)

                    approve.scroll_into_view_if_needed()
                    approve.hover()
                    time.sleep(1.5)
                    approve.click()
                    _mark(timeline, started, "autonomous_approval_clicked")

                    # Progress remains where the approval happened. Reacquire the
                    # action-local rail after Streamlit's rerender, but do not move the
                    # camera to a second status surface.
                    time.sleep(0.8)
                    status = page.locator('[aria-label="Verified workflow progress"]')
                    if status.count() != 1:
                        raise RuntimeError(
                            "The action-local workflow rail was missing or duplicated."
                        )
                    status.wait_for(state="visible", timeout=10_000)
                    _mark(timeline, started, "show:live_workflow_status")
                    progress_values: list[int] = []

                    def sample_progress() -> None:
                        text = status.inner_text()
                        match = re.search(r"\b(\d{1,3})%", text)
                        if not match:
                            raise RuntimeError(
                                "The visible workflow rail did not expose a percentage."
                            )
                        value = int(match.group(1))
                        if progress_values and value < progress_values[-1]:
                            raise RuntimeError(
                                "Workflow progress moved backward: "
                                f"{progress_values[-1]}% -> {value}%."
                            )
                        if not progress_values or value != progress_values[-1]:
                            progress_values.append(value)
                            _mark(timeline, started, f"progress:{value}")

                    sample_progress()

                    complete = page.get_by_text(
                        (
                            "One-click workflow completed this proposal through sandbox "
                            "verification and the selected finish action. Manual controls remain "
                            "available in Advanced settings for a new run."
                        ),
                        exact=True,
                    )
                    failure = page.get_by_text(
                        "The autonomous workflow stopped before completion.",
                        exact=False,
                    )
                    cancel = page.get_by_role(
                        "button", name="Cancel current run", exact=True
                    )
                    cancel_seen = False
                    returned_at: float | None = None
                    deadline = time.monotonic() + 150
                    while time.monotonic() < deadline:
                        sample_progress()
                        if complete.count() and complete.first.is_visible():
                            break
                        if failure.count() and failure.first.is_visible():
                            raise RuntimeError(failure.first.inner_text())
                        if cancel.count() and cancel.first.is_visible():
                            cancel_seen = True
                        if (
                            cancel_seen
                            and approve.count()
                            and approve.first.is_visible()
                        ):
                            # The start control is near the top of the final rerun and
                            # can paint before the receipt below it. Give that same rerun
                            # a bounded window to finish rendering.
                            returned_at = returned_at or time.monotonic()
                            if time.monotonic() - returned_at > 15:
                                body_text = page.locator("body").inner_text()
                                (VIDEO_DIR / "failed-autonomous-body.txt").write_text(
                                    body_text, encoding="utf-8"
                                )
                                page.screenshot(
                                    path=str(VIDEO_DIR / "failed-autonomous-page.png"),
                                    full_page=True,
                                )
                                raise RuntimeError(
                                    "The final rerun did not render a success or failure "
                                    "receipt. Inspect failed-autonomous-body.txt."
                                )
                        time.sleep(0.5)
                    else:
                        body_text = page.locator("body").inner_text()
                        (VIDEO_DIR / "failed-autonomous-body.txt").write_text(
                            body_text, encoding="utf-8"
                        )
                        page.screenshot(
                            path=str(VIDEO_DIR / "failed-autonomous-page.png"),
                            full_page=True,
                        )
                        raise PlaywrightTimeoutError(
                            "Timed out waiting for an autonomous success/failure receipt."
                        )
                    status.wait_for(state="visible", timeout=10_000)
                    sample_progress()
                    if progress_values[-1] != 100:
                        raise RuntimeError(
                            "The verified workflow completed without a visible 100% rail: "
                            f"{progress_values}."
                        )
                    if len(progress_values) < 4:
                        raise RuntimeError(
                            "The visible workflow rail did not show enough real phase movement: "
                            f"{progress_values}."
                        )
                    _mark(timeline, started, "autonomous_workflow_complete")
                    time.sleep(3)

                    _show(
                        page,
                        "Lineage the agent walked",
                        timeline,
                        started,
                        pause=4,
                    )
                    _show(page, "Diagnosis", timeline, started, pause=5)
                    _show(
                        page,
                        "2 · Review the proposed code change",
                        timeline,
                        started,
                        pause=4,
                    )
                    exact_diff = page.get_by_role("tab", name="Exact diff", exact=True)
                    exact_diff.click()
                    exact_diff.scroll_into_view_if_needed()
                    _mark(timeline, started, "show:Exact diff")
                    time.sleep(7)

                    _show(
                        page,
                        "3 · Sandbox verification receipt",
                        timeline,
                        started,
                        pause=7,
                    )
                    complete.scroll_into_view_if_needed()
                    _mark(timeline, started, "show:autonomous_completion")
                    time.sleep(5)
                    _show(
                        page,
                        "4 · Verified human handoff",
                        timeline,
                        started,
                        pause=20,
                    )
                    _mark(timeline, started, "capture_complete")
                finally:
                    _stop_capture(capture)
                    context.close()

    TIMELINE.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    if not RAW_VIDEO.is_file() or RAW_VIDEO.stat().st_size < 1_000_000:
        raise SystemExit(f"The live capture was not produced. Inspect {FFMPEG_LOG}.")
    events = {item["event"] for item in timeline}
    required = {
        "autonomous_approval_clicked",
        "show:live_workflow_status",
        "autonomous_workflow_complete",
        "progress:100",
        "show:Exact diff",
        "show:3 · Sandbox verification receipt",
        "show:4 · Verified human handoff",
        "capture_complete",
    }
    if missing := required - events:
        raise SystemExit(f"Recording did not reach required live states: {sorted(missing)}")
    print(RAW_VIDEO)
    print(TIMELINE)


if __name__ == "__main__":
    main()
