import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against a live stack:
 *   backend  : uvicorn app.main:app --port 8000
 *   frontend : next start --port 3000 (CONTEXTFORGE_PUBLIC_API_URL=http://127.0.0.1:8000)
 *   fake LLM : python -m tests.fake_llm_server --port 9100 (OpenAI-compatible, deterministic)
 * See scripts/e2e.sh.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000",
    trace: "off",
    viewport: { width: 1440, height: 960 },
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 960 } } }],
});
