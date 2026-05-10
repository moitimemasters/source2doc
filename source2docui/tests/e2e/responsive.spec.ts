import { devices, expect, test } from "@playwright/test";

/**
 * Adaptive layout / responsive tests.
 *
 * The default `mobile` Playwright project (configured in playwright.config.ts)
 * uses Pixel 7 viewport and would already inherit it via `use:`. We pin the
 * viewport here as well so this spec also makes sense when run under the
 * desktop projects (e.g. `--project=chromium`) — important because B12.2
 * gates verification on a quick `--project=chromium --grep responsive` run.
 *
 * No real backend: every gateway endpoint is mocked.
 */
test.use({ viewport: devices["Pixel 7"].viewport });

test.describe("responsive — mobile viewport", () => {
    test("home page renders header navigation icons on narrow screens", async ({
        page,
    }) => {
        await page.goto("/");

        // Header is sticky and rendered on every page. The text labels are
        // hidden below `sm` breakpoint (`hidden sm:inline`), but the
        // nav links remain accessible via `aria-label`. Scope to the
        // <header> (role="banner") because the home page body also
        // contains a link with text "Streams" that would otherwise
        // collide with the header nav icon under exact match.
        const header = page.getByRole("banner");
        await expect(
            header.getByRole("link", { name: "Home", exact: true }),
        ).toBeVisible();
        await expect(
            header.getByRole("link", { name: "Streams", exact: true }),
        ).toBeVisible();
        await expect(
            header.getByRole("link", { name: "Admin", exact: true }),
        ).toBeVisible();

        // Hub heading still visible.
        await expect(
            page.getByRole("heading", { name: /Documentation Hub/i }),
        ).toBeVisible();
    });

    test("Generate Docs CTA collapses to short label on mobile", async ({
        page,
    }) => {
        await page.goto("/");

        // The button has `+ Docs` on mobile (sm:hidden) and `Generate Docs`
        // on desktop (hidden sm:inline). On Pixel 7 we should see "+ Docs".
        await expect(
            page.getByRole("button", { name: /\+ Docs/ }).first(),
        ).toBeVisible();
    });

    test("streams empty state renders on mobile", async ({ page }) => {
        await page.route("**/api/gateway/streams", (route) =>
            route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({ streams: [] }),
            }),
        );

        await page.goto("/streams");

        // No horizontal overflow — confirm the body is visible and laid out.
        await expect(page.locator("body")).toBeVisible();
        await expect(
            page.locator("text=/no.+stream|empty/i").first(),
        ).toBeVisible();

        // Header nav icons are still reachable on mobile.
        await expect(
            page.getByRole("link", { name: "Home", exact: true }),
        ).toBeVisible();
    });

    test("admin dashboard remains navigable on mobile", async ({
        page,
        context,
    }) => {
        await context.addCookies([
            {
                name: "s2d_admin",
                value: "test-session",
                domain: "localhost",
                path: "/",
            },
        ]);

        await page.goto("/admin");

        // Admin dashboard links remain accessible on narrow viewports.
        await expect(
            page.getByRole("heading", { name: /^Admin$/ }),
        ).toBeVisible();
        await expect(
            page.getByRole("link", { name: /Repositories/i }),
        ).toBeVisible();
    });

    test("page does not produce horizontal scroll at 412px width", async ({
        page,
    }) => {
        await page.goto("/");

        // Pixel 7 is 412×915. Document width should not exceed viewport
        // width — i.e. no accidental fixed-width content forcing a horizontal
        // scrollbar.
        const overflow = await page.evaluate(() => {
            return (
                document.documentElement.scrollWidth >
                document.documentElement.clientWidth
            );
        });
        expect(overflow).toBe(false);
    });
});
