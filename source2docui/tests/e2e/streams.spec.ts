import { expect, test } from "@playwright/test";

/**
 * /streams page tests — list view fetches GET /api/gateway/streams every
 * 5s. We mock the response so the test is fast and independent of the
 * gateway being up.
 */

const FIXED_STREAM_ID = "11111111-2222-3333-4444-555555555555";

const mockStreamsList = (count: number) => ({
    streams: Array.from({ length: count }, (_, i) => ({
        stream_id: `${FIXED_STREAM_ID.slice(0, -1)}${i}`,
        event_count: 12 + i,
        last_event_id: "1700000000000-0",
        name: `Demo project ${i + 1}`,
        description: "Generated documentation",
        status: i === 0 ? "running" : "completed",
        repo_id: "00000000-0000-0000-0000-00000000aaaa",
        repository: {
            name: `repo-${i + 1}`,
            source_type: "git",
            git_url: `https://github.com/example/repo-${i + 1}.git`,
            git_branch: "main",
        },
        created_at: "2026-05-04T00:00:00+00:00",
        started_at: "2026-05-04T00:00:00+00:00",
        completed_at: i === 0 ? null : "2026-05-04T00:05:00+00:00",
    })),
});

test("renders empty state when no streams", async ({ page }) => {
    await page.route("**/api/gateway/streams", (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ streams: [] }),
        }),
    );

    await page.goto("/streams");
    // Empty state copy lives in components/streams/EmptyState.tsx — just
    // assert *something* renders (no infinite spinner / crash).
    await expect(page.locator("body")).toBeVisible();
    await expect(page.locator("text=/no.+stream|empty/i").first()).toBeVisible();
});

test("renders stream cards from mocked API", async ({ page }) => {
    await page.route("**/api/gateway/streams", (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(mockStreamsList(3)),
        }),
    );

    await page.goto("/streams");

    await expect(page.getByText("Demo project 1")).toBeVisible();
    await expect(page.getByText("Demo project 2")).toBeVisible();
    await expect(page.getByText("Demo project 3")).toBeVisible();
});

test("stream cards link to detail page", async ({ page }) => {
    await page.route("**/api/gateway/streams", (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(mockStreamsList(1)),
        }),
    );

    await page.goto("/streams");

    const firstCard = page.getByText("Demo project 1");
    await expect(firstCard).toBeVisible();

    const link = page.locator("a[href*='/streams/']").first();
    await expect(link).toHaveAttribute("href", /\/streams\/.+/);
});

test("error state shown when gateway returns 5xx", async ({ page }) => {
    await page.route("**/api/gateway/streams", (route) =>
        route.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({ error: "service unavailable" }),
        }),
    );

    await page.goto("/streams");
    // ErrorState component shows some "error" copy.
    await expect(page.locator("text=/error|fail/i").first()).toBeVisible();
});
