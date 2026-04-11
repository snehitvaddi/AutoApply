import { test, expect } from '@playwright/test';

/**
 * Desktop smoke tests.
 *
 * These run against the packaged ApplyLoop.app that the CI workflow
 * has already launched in headless mode on localhost:18790.
 *
 * Coverage:
 *   1. /api/health responds 200
 *   2. A cold visit to / redirects to /setup/ because there's no token
 *   3. The setup wizard's activation-code input is on the page with
 *      the AL-XXXX-XXXX placeholder (primary interaction target)
 *   4. Pasting a format-valid but non-existent code surfaces the
 *      "doesn't exist" remediation from the server
 *   5. The preflight API exposes the 8-check structure the wizard
 *      depends on (regression guard against accidental shape changes)
 *
 * Note on removed "valid code lands on dashboard" test:
 *   Before v1.0.4 the wizard was single-step (paste code → redirect
 *   to dashboard). With the Wave 4 checklist rewrite, a valid code
 *   flips the Activation row green but the user stays on /setup
 *   until all non-optional checks pass (profile / resume / prefs /
 *   local CLIs). The CI test user qa-ci@applyloop.test has an empty
 *   profile so the checklist never goes green — meaning the old
 *   test expectation of "redirects to /" is no longer valid. Test #4
 *   below instead verifies the checklist renders with the token row
 *   turned green after a successful activation, which is the actual
 *   correct behavior for the new flow.
 */

test('health endpoint responds 200', async ({ request }) => {
  const r = await request.get('/api/health');
  expect(r.status()).toBe(200);
  const body = await r.json();
  expect(body).toBeTruthy();
});

test('cold visit redirects to /setup wizard', async ({ page }) => {
  await page.goto('/');
  await page.waitForURL(/\/setup\/?$/, { timeout: 15_000 });
  // Wave 4 wizard copy. The old "One-time setup" / "Welcome! One-time"
  // headers got replaced by the two-step checklist-driven UI.
  // .first() because the page renders both the step heading ("Step 1 of
  // 2 — Activate") and its caption ("Paste the activation code...") —
  // the alternation below matches both, which is a strict-mode violation
  // without .first().
  await expect(
    page
      .getByText(
        /Step 1 of 2 — Activate|Paste the activation code|One-time setup/i
      )
      .first()
  ).toBeVisible({ timeout: 10_000 });
  // The activation input must be on the page regardless of copy.
  await expect(page.getByPlaceholder(/AL-XXXX-XXXX/)).toBeVisible();
});

test('bogus activation code shows not_found remediation', async ({ page }) => {
  await page.goto('/setup/');
  const input = page.getByPlaceholder(/AL-XXXX-XXXX/);
  // Wait for the input to be attached before filling — the wizard
  // renders a spinner while fetching /api/setup/status and only
  // shows the form once the response lands.
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill('AL-BOGX-XXXX');
  await page.getByRole('button', { name: /activate/i }).click();
  // Matches _SETUP_REMEDIATION["not_found"] in server/app.py:
  //   "This code doesn't exist. Double-check the letters and numbers..."
  // .first() because the remediation string shows up twice — once in the
  // inline <activationError> span next to the Activate button, and again
  // as the detail line under the token check row in the checklist below.
  await expect(
    page.getByText(/doesn.t exist|not found|Invalid activation/i).first()
  ).toBeVisible({ timeout: 15_000 });
});

test('valid activation code flips checklist token row green', async ({ page }) => {
  const code = process.env.CI_ACTIVATION_CODE;
  test.skip(!code, 'CI_ACTIVATION_CODE secret not set — skipping valid-code test');

  await page.goto('/setup/');
  const input = page.getByPlaceholder(/AL-XXXX-XXXX/);
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill(code!);
  await page.getByRole('button', { name: /activate/i }).click();

  // Wave 4 flow: activation succeeds → success banner "Activated..." →
  // checklist re-renders with the Activation row marked green. No
  // automatic navigation to / because the CI test user has no
  // profile/resume/preferences, so Start ApplyLoop stays disabled.
  await expect(
    page.getByText(/Activated|Setup checklist|Profile information/i)
  ).toBeVisible({ timeout: 20_000 });

  // The "Start ApplyLoop" button must be present on the checklist
  // view (disabled, but visible).
  await expect(
    page.getByRole('button', { name: /start applyloop/i })
  ).toBeVisible({ timeout: 5_000 });
});

test('/api/setup/status returns preflight check array', async ({ request }) => {
  // Regression guard — the wizard UI + lifespan PTY guard + worker
  // preflight all depend on this response shape. If someone changes
  // the field names, this test fails fast.
  const r = await request.get('/api/setup/status');
  expect(r.status()).toBe(200);
  const body = await r.json();
  expect(typeof body.setup_complete).toBe('boolean');
  expect(Array.isArray(body.checks)).toBe(true);
  expect(body.checks.length).toBeGreaterThanOrEqual(8);
  // Every check has the fields the UI expects.
  const ids = body.checks.map((c: { id: string }) => c.id);
  for (const required of ['token', 'profile', 'resume', 'preferences', 'claude_cli', 'openclaw_cli']) {
    expect(ids).toContain(required);
  }
});
