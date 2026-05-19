import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
const isLocal = /^https?:\/\/(localhost|127\.0\.0\.1)(:|$)/.test(BASE_URL);

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: BASE_URL,
    // Pin Accept-Language so locale-negotiation redirects (`/` → `/en`)
    // are deterministic across local CI agents and contributor laptops.
    extraHTTPHeaders: { "Accept-Language": "en-US,en;q=0.9" },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 5"] },
    },
  ],

  // Only spawn the dev server when we're targeting localhost. Pointing
  // BASE_URL at staging/prod skips webServer entirely so CI doesn't try
  // to bind port 3000 just to smoke a remote URL.
  webServer: isLocal
    ? {
        command: "npm run dev",
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        stdout: "pipe",
        stderr: "pipe",
      }
    : undefined,
});
