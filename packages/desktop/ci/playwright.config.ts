import { defineConfig, devices } from '@playwright/test';

// Playwright config for the desktop CI smoke suite.
// The ApplyLoop desktop app is expected to already be running on
// $BASE_URL (default http://localhost:18790) — the workflow's Launch
// step handles that. We do NOT spin up a webServer here.
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,         // SQLite file lock — don't parallelize
  forbidOnly: !!process.env.CI, // Block accidental .only in merged PRs
  retries: process.env.CI ? 1 : 0,
  workers: 1,                    // serial runner; all tests hit the same app
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:18790',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
