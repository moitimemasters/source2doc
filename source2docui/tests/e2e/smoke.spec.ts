import { expect, test } from "@playwright/test";

/**
 * Smoke tests — every navigable page renders without console errors and
 * shows its main heading. No backend required (server-rendered Home reads
 * the empty default registry; client pages mock /api/* per-page elsewhere).
 */

test.describe("smoke", () => {
    test("home page renders header + nav links", async ({ page }) => {
        await page.goto("/");

        await expect(
            page.getByRole("heading", { name: /Documentation Hub/i }),
        ).toBeVisible();
        await expect(
            page.getByRole("link", { name: /Monitor Generation Streams/i }),
        ).toBeVisible();
        await expect(
            page.getByRole("link", { name: /Export Bundles/i }),
        ).toBeVisible();
    });

    test.describe("admin (gated by s2d_admin cookie)", () => {
        test.beforeEach(async ({ context }) => {
            // /admin/* is gated by Next.js proxy.ts — placeholder cookie
            // bypasses the redirect to /admin/login.
            await context.addCookies([
                {
                    name: "s2d_admin",
                    value: "test-session",
                    domain: "localhost",
                    path: "/",
                },
            ]);
        });

        test("dashboard renders section cards", async ({ page }) => {
            // The standalone /generate page was removed upstream — generation
            // now lives at /admin/generate behind the dashboard.
            await page.goto("/admin");

            await expect(
                page.getByRole("heading", { name: /^Admin$/ }),
            ).toBeVisible();
            // Card titles render as <div> via shadcn CardTitle, not <h*>.
            // Assert via the link nav targets instead.
            await expect(
                page.getByRole("link", { name: /Presets/i }),
            ).toBeVisible();
            await expect(
                page.getByRole("link", { name: /Repositories/i }),
            ).toBeVisible();
            await expect(
                page.getByRole("link", { name: /Generate documentation/i }),
            ).toBeVisible();
        });

        test("repos page renders empty state", async ({ page }) => {
            await page.route("**/api/gateway/repos", (route) =>
                route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({ repositories: [], count: 0 }),
                }),
            );

            await page.goto("/admin/repos");
            await expect(
                page.getByRole("heading", { name: /^Repositories$/ }),
            ).toBeVisible();
        });
    });

    test("bundles page renders", async ({ page }) => {
        await page.route("**/api/gateway/docs/bundles**", (route) =>
            route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({ bundles: [] }),
            }),
        );

        await page.goto("/bundles");
        await expect(page.locator("body")).toBeVisible();
    });
});
