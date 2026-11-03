import { defineConfig, devices } from "@playwright/test"

/**
 * E2E tests run against a running stack (`docker compose up`).
 *   E2E_BASE_URL   default http://localhost:3000
 *   E2E_VIDEO      video to upload (default ../test-media/e2e-cs.mp4)
 *   CHROMIUM_PATH  optional custom Chromium binary
 */
const launchOptions = process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}

export default defineConfig({
  testDir: "./e2e",
  timeout: 45 * 60 * 1000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], launchOptions } },
    { name: "mobile", use: { ...devices["Pixel 7"], launchOptions }, testMatch: /mobile\.spec\.ts/ },
  ],
})
