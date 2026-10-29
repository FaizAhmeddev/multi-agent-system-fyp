import { defineConfig, devices } from "@playwright/test";

// End-to-end tests against a running AgentsMind (core API serving frontend/dist, portals and MCP servers
// in sandbox mode). The phase gate starts everything; locally: scripts\win\run_all.ps1, then `npm run e2e`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: process.env.AGENTSMIND_URL ?? "http://127.0.0.1:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1360, height: 900 } } }],
});
