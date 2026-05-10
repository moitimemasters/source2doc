import { expect, test } from "@playwright/test";

// /admin/* is gated by an `s2d_admin` cookie via the Next.js proxy
// (source2docui/proxy.ts). The proxy doesn't validate the cookie value —
// just its presence. Set a placeholder so the redirect to /admin/login
// doesn't kick in for these tests.
test.beforeEach(async ({ context }) => {
    await context.addCookies([
        {
            name: "s2d_admin",
            value: "test-session",
            domain: "localhost",
            path: "/",
        },
    ]);
});

const mockRepos = (count: number) => ({
    repositories: Array.from({ length: count }, (_, i) => ({
        repo_id: `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`,
        name: `repo-${i + 1}`,
        source_type: "git",
        git_url: `https://github.com/example/repo-${i + 1}.git`,
        git_branch: "main",
        s3_key: `repos/repo-${i + 1}.tar.gz`,
        description: `Demo repository ${i + 1}`,
        created_at: "2026-05-04T00:00:00+00:00",
        updated_at: "2026-05-04T00:00:00+00:00",
    })),
    count,
});

test("renders repository list from mocked API", async ({ page }) => {
    await page.route("**/api/gateway/repos", (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(mockRepos(2)),
        }),
    );

    await page.goto("/admin/repos");

    await expect(
        page.getByRole("heading", { name: /^Repositories$/ }),
    ).toBeVisible();
    // The git URL contains "repo-1" too — use exact match.
    await expect(page.getByText("repo-1", { exact: true })).toBeVisible();
    await expect(page.getByText("repo-2", { exact: true })).toBeVisible();
    await expect(page.getByText("Demo repository 1")).toBeVisible();
});

test("shows git URL with branch suffix", async ({ page }) => {
    await page.route("**/api/gateway/repos", (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(mockRepos(1)),
        }),
    );

    await page.goto("/admin/repos");

    await expect(
        page.getByText("https://github.com/example/repo-1.git"),
    ).toBeVisible();
});

test("renders empty state when no repos returned", async ({ page }) => {
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
    // No "repo-" entries.
    await expect(page.getByText(/^repo-\d/)).toHaveCount(0);
});
