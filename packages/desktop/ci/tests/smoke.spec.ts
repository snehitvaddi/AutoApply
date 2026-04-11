import { test, expect } from '@playwright/test';

/**
 * Desktop smoke tests.
 *
 * These run against the packaged ApplyLoop.app that the CI workflow
 * has already launched in headless mode on localhost:18790. They cover
 * the four assertions that most directly validate "a random user
 * downloaded the .dmg, pasted an activation code, and the app works":
 *
 *   1. /api/health responds 200 at all
 *   2. A cold visit to / redirects to /setup because there's no token file
 *   3. A bogus activation code shows the not_found remediation message
 *   4. The real long-lived CI activation code (AL-CICI-TEST) redeems
 *      successfully and the UI lands on the dashboard
 *
 * Tests 1-3 don't need any secrets. Test 4 needs CI_ACTIVATION_CODE
 * to be set as a GitHub Actions secret pointing at the real code.
 * If unset, test 4 is skipped rather than failed — so PRs from forks
 * (which can't read repo secrets) don't break the whole suite.
 */

test('health endpoint responds 200', async ({ request }) => {
  const r = await request.get('/api/health');
  expect(r.status()).toBe(200);
  const body = await r.json();
  // Supports both the {ok: true, worker: {...}} shape and the
  // {status: "ok"} shape depending on which endpoint variant is active.
  expect(body).toBeTruthy();
});

test('cold visit redirects to /setup wizard', async ({ page }) => {
  await page.goto('/');
  await page.waitForURL(/\/setup\/?$/, { timeout: 15_000 });
  // The wizard header from ui/app/setup/page.tsx
  await expect(page.getByText(/One-time setup|Welcome! One-time/i)).toBeVisible();
  await expect(page.getByPlaceholder(/AL-XXXX-XXXX/)).toBeVisible();
});

test('bogus activation code shows not_found remediation', async ({ page }) => {
  await page.goto('/setup/');
  const input = page.getByPlaceholder(/AL-XXXX-XXXX/);
  // Type a format-valid but non-existent code so the client regex lets
  // us submit. The server will respond with code=not_found.
  await input.fill('AL-BOGX-XXXX');
  await page.getByRole('button', { name: /activate/i }).click();
  // Matches _SETUP_REMEDIATION["not_found"] in server/app.py:
  //   "This code doesn't exist. Double-check the letters and numbers..."
  await expect(
    page.getByText(/doesn.t exist|not found|Invalid activation/i)
  ).toBeVisible({ timeout: 15_000 });
});

test('valid activation code lands on dashboard', async ({ page }) => {
  const code = process.env.CI_ACTIVATION_CODE;
  test.skip(!code, 'CI_ACTIVATION_CODE secret not set — skipping valid-code test');

  await page.goto('/setup/');
  await page.getByPlaceholder(/AL-XXXX-XXXX/).fill(code!);
  await page.getByRole('button', { name: /activate/i }).click();
  // Success screen shows "Welcome" + (optional name) + "Loading your dashboard…"
  await expect(page.getByText(/Welcome/)).toBeVisible({ timeout: 20_000 });
  // Then bounces to the root dashboard after ~1.8s
  await page.waitForURL(/\/($|\?|#)/, { timeout: 10_000 });
  // Dashboard content should be visible — check for stat cards or sidebar nav
  await expect(
    page.locator('text=/Dashboard|Pipeline|Applications/i').first()
  ).toBeVisible({ timeout: 10_000 });
});
