import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for source2docui.
 *
 * Tests boot a Next.js dev server (or reuse one if already running on 3000)
 * and drive it via headless browsers. Backend (gateway) calls are mocked
 * per-test with `page.route()` so the suite is hermetic — no real API or
 * filesystem dependencies.
 *
 * Cross-browser projects: chromium, firefox, webkit, edge, mobile.
 * Edge is a Chromium variant via `channel: "msedge"` and is omitted from CI
 * (covered by the `chromium` matrix entry — see `.github/workflows/e2e.yml`).
 */
export default defineConfig({
    testDir: "./tests/e2e",
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 1 : 0,
    workers: process.env.CI ? 2 : undefined,
    reporter: [["list"], ["html", { open: "never" }]],
    use: {
        baseURL: "http://localhost:3000",
        trace: "retain-on-failure",
        screenshot: "only-on-failure",
    },
    projects: [
        {
            name: "chromium",
            use: { ...devices["Desktop Chrome"] },
        },
        {
            name: "firefox",
            use: { ...devices["Desktop Firefox"] },
        },
        {
            name: "webkit",
            use: { ...devices["Desktop Safari"] },
        },
        {
            name: "edge",
            use: { ...devices["Desktop Edge"], channel: "msedge" },
        },
        {
            name: "mobile",
            use: { ...devices["Pixel 7"] },
        },
    ],
    webServer: {
        command: "bun run dev",
        url: "http://localhost:3000",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        stdout: "pipe",
        stderr: "pipe",
    },
});
