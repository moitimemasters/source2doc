# UI Testing

End-to-end via [Playwright](https://playwright.dev). Hermetic — gateway calls mocked per-test with `page.route()`, no backend required.

## Setup

```bash
cd source2docui
bun install                      # picks up @playwright/test devDep
bun run test:e2e:install         # one-time chromium download (~95 MB)
```

## Run

```bash
bun run test:e2e          # headless, ~6s, 13 tests
bun run test:e2e:ui       # interactive UI mode for debugging
bunx playwright test admin.spec.ts                                # single file
bunx playwright test --grep "renders empty state"                 # by name
bunx playwright test --headed                                     # see the browser
bunx playwright show-report                                       # open last HTML report
```

The runner auto-spawns `next dev` on port 3000 (reused if already running).

## Layout

```
source2docui/
├── playwright.config.ts          # webServer auto-spawns next dev, chromium only
└── tests/e2e/
    ├── smoke.spec.ts             # home, generate, admin, bundles render
    ├── streams.spec.ts           # /streams list, empty + error states
    ├── admin.spec.ts             # /admin repository list with mocked /api/gateway/repos
    └── generate.spec.ts          # /generate form mounts
```

## Mocking the backend

UI hits `/api/gateway/*` (Next.js proxy) → real gateway. Tests intercept those:

```ts
await page.route("**/api/gateway/repos", (route) =>
    route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ repositories: [], count: 0 }),
    }),
);
await page.goto("/admin");
```

Match the gateway DTO from `lib/gateway/types.ts` — `StreamListResponseSchema`, etc.

## Adding a test

1. Drop a `*.spec.ts` under `tests/e2e/`.
2. Mock every `/api/gateway/*` and `/api/projects` your page hits.
3. Use `getByRole` / `getByText({ exact: true })` over CSS selectors.
4. Run `bun run test:e2e` — the suite must stay under ~10s total.

## CI hint

```bash
bun install
bun run test:e2e:install
bun run test:e2e
```
