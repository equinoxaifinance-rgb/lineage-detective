"""LEGACY screenshot collector retained for historical reproduction only.

This is not the current judge-video path. The release candidate is recorded as one uninterrupted
browser workflow by ``tools/record_judge_demo.py``.
"""
import os
from playwright.sync_api import sync_playwright

os.makedirs("cap", exist_ok=True)
CASES = [
    ("A_revenue",  "Revenue dashboard dropped 40% (silent partial load)"),
    ("B_customer", "Customer 360 emails went blank (schema drift)"),
    ("C_finance",  "Finance USD revenue looks frozen (stale data)"),
]

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 1600})
    pg.goto("http://localhost:8501", wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(2500)
    pg.screenshot(path="cap/00_home.png", full_page=True)
    print("home captured")

    for i, (tag, label) in enumerate(CASES):
        try:
            pg.get_by_role("combobox").first.click()
            pg.wait_for_timeout(600)
            pg.get_by_role("option", name=label).click()
            pg.wait_for_timeout(900)
        except Exception as e:
            print(tag, "select warn:", str(e)[:80])
        pg.get_by_role("button", name="Investigate").click()
        # wait for the investigation to finish rendering (suspects appear)
        pg.wait_for_selector("text=Root-cause suspects", timeout=120000)
        pg.wait_for_timeout(2500)  # let blast-radius section paint
        pg.screenshot(path=f"cap/{i+1:02d}_{tag}.png", full_page=True)
        print(tag, "captured")
    b.close()

print("ALL UI FRAMES CAPTURED:", sorted(os.listdir("cap")))
