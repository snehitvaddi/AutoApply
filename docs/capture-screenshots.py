"""Capture authenticated screenshots for CLIENT-ONBOARDING.md.

Usage:
    1. Open Chrome and log into https://autoapply-web.vercel.app
    2. Close Chrome completely (Cmd+Q)
    3. Run: python3 docs/capture-screenshots.py

This uses your Chrome profile's session cookies to capture all pages.
Screenshots are saved to docs/images/.
"""

import asyncio
import os
from playwright.async_api import async_playwright

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "images")
CHROME_PROFILE = os.path.expanduser("~/Library/Application Support/Google/Chrome")
BASE = "https://autoapply-web.vercel.app"

PAGES = [
    (f"{BASE}/auth/login", "01-login-page.png"),
    (f"{BASE}/auth/pending", "03-pending-approval.png"),
    (f"{BASE}/onboarding", "04-onboarding-step1-ai-import.png"),
    (f"{BASE}/dashboard", "09-dashboard-overview.png"),
    (f"{BASE}/dashboard/jobs", "10-dashboard-jobs.png"),
    (f"{BASE}/dashboard/applications", "11-dashboard-applications.png"),
    (f"{BASE}/dashboard/settings", "12-settings-ai-import.png"),
    (f"{BASE}/admin", "15-admin-panel.png"),
]

# Onboarding sub-steps (navigate programmatically after loading onboarding)
ONBOARDING_STEPS = [
    # After loading /onboarding, click Next to advance through steps
    ("Step 2: Personal Info", "05-onboarding-step2-personal.png"),
    ("Step 3: Work & Education", "06-onboarding-step3-work.png"),
    ("Step 4: Job Preferences", "07-onboarding-step4-preferences.png"),
    ("Step 5: Resume Upload", "08-onboarding-step5-resume.png"),
]

# Settings tabs
SETTINGS_TABS = [
    ("Resumes", "13-settings-resumes.png"),
    ("Telegram", "14-settings-telegram.png"),
]


async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            CHROME_PROFILE,
            headless=False,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            device_scale_factor=2,
        )

        page = context.pages[0] if context.pages else await context.new_page()

        for url, filename in PAGES:
            path = os.path.join(OUTPUT_DIR, filename)
            print(f"Capturing {url}")
            try:
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(1500)

                final = page.url
                if "/auth/login" in final and "/auth/login" not in url:
                    print(f"  SKIP — redirected to login (not authenticated)")
                    continue

                await page.screenshot(path=path, full_page=True)
                print(f"  Saved: {filename}")

                # If on onboarding page, capture sub-steps
                if "/onboarding" in url and "/auth/" not in final:
                    for step_name, step_file in ONBOARDING_STEPS:
                        try:
                            next_btn = page.locator("button:has-text('Next')")
                            if await next_btn.is_visible():
                                await next_btn.click()
                                await page.wait_for_timeout(500)
                                step_path = os.path.join(OUTPUT_DIR, step_file)
                                await page.screenshot(path=step_path, full_page=True)
                                print(f"  Saved: {step_file} ({step_name})")
                        except Exception as e:
                            print(f"  Could not capture {step_name}: {e}")

                # If on settings page, capture tabs
                if "/settings" in url and "/auth/" not in final:
                    for tab_name, tab_file in SETTINGS_TABS:
                        try:
                            tab_btn = page.locator(f"button:has-text('{tab_name}')")
                            if await tab_btn.is_visible():
                                await tab_btn.click()
                                await page.wait_for_timeout(500)
                                tab_path = os.path.join(OUTPUT_DIR, tab_file)
                                await page.screenshot(path=tab_path, full_page=True)
                                print(f"  Saved: {tab_file} ({tab_name} tab)")
                        except Exception as e:
                            print(f"  Could not capture {tab_name} tab: {e}")

            except Exception as e:
                print(f"  Error: {e}")

        await context.close()

    print(f"\nDone! Screenshots in {OUTPUT_DIR}/")
    print("Tip: For authenticated pages, make sure Chrome is fully closed before running.")


if __name__ == "__main__":
    asyncio.run(main())
