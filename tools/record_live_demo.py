"""Record one real, isolated-browser Lineage Detective judge run.

This is media tooling only. It launches Chrome with a disposable profile, opens the
already-running local no-key judge app, clicks Investigate, waits for the real MCP
result, and records that dedicated window through ffmpeg. It never opens an existing
browser profile or captures the desktop.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "vid" / "lineage-detective-live-judge-run.mp4"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def main() -> None:
    if not CHROME.is_file():
        raise SystemExit("Chrome was not found at the expected executable path.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required for the live recording.")
    OUT.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lineage-detective-video-") as profile:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                profile,
                executable_path=str(CHROME),
                headless=False,
                viewport={"width": 1280, "height": 720},
                # Windows' desktop capture sees a blank surface for some GPU-composited
                # Chrome windows. Disable GPU only in this disposable recording browser.
                args=["--window-size=1280,850", "--force-device-scale-factor=1", "--disable-gpu", "--test-type"],
            )
            page = browser.pages[0]
            page.goto("http://127.0.0.1:8503/", wait_until="domcontentloaded")
            page.get_by_role("button", name="Investigate", exact=True).wait_for()
            # Let the browser paint the genuine initial screen before capture starts.
            time.sleep(2)
            capture = subprocess.Popen([
                ffmpeg, "-y", "-f", "gdigrab", "-framerate", "30",
                "-i", "title=Lineage Detective - Google Chrome", "-t", "36",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                time.sleep(2)
                page.get_by_role("button", name="Investigate", exact=True).click()
                # This waits on the observed report, not a guessed duration.
                page.get_by_text("Evidence-only judge mode", exact=False).wait_for(timeout=50_000)
                time.sleep(3)
                page.mouse.wheel(0, 560)
                time.sleep(5)
                page.mouse.wheel(0, 480)
                time.sleep(5)
                capture.wait(timeout=20)
            finally:
                if capture.poll() is None:
                    capture.terminate()
                    capture.wait(timeout=5)
                browser.close()
    if not OUT.is_file() or OUT.stat().st_size < 100_000:
        raise SystemExit("The live capture was not produced.")
    print(OUT)


if __name__ == "__main__":
    main()
