import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const SAMPLES = path.resolve(__dirname, "../../samples/dist");
const API = process.env.E2E_API_URL || "http://127.0.0.1:8000";
const FAKE_LLM = process.env.E2E_FAKE_LLM_URL || "http://127.0.0.1:9100/v1";

test.describe.serial("ContextForge end-to-end", () => {
  test.beforeAll(() => {
    expect(fs.existsSync(path.join(SAMPLES, "python-fastapi-shop.zip")), "run scripts/make_sample_zips.py first").toBeTruthy();
  });

  test("workspace loads and reports API connectivity", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Forge a complete, source-referenced knowledge base/ })).toBeVisible();
    await expect(page.getByText(/API connected/)).toBeVisible();
  });

  test("configure an OpenAI-compatible provider and test the connection", async ({ page }) => {
    await page.goto("/settings");
    await page.getByLabel("Provider", { exact: true }).selectOption("openai_compatible");
    await page.getByLabel("Model", { exact: true }).fill("fake-local-model");
    await page.getByLabel("Base URL", { exact: true }).fill(FAKE_LLM);
    await page.getByRole("button", { name: "Save provider" }).click();
    await expect(page.getByText("Provider settings saved")).toBeVisible();
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(page.getByText(/Connected to fake-local-model/)).toBeVisible();
    await page.getByRole("button", { name: "List models" }).click();
    await expect(page.getByText(/1 models available/)).toBeVisible();
  });

  test("upload, analyse with the LLM provider, explore and download", async ({ page }) => {
    await page.goto("/new");
    await page.setInputFiles("[data-testid=file-input]", path.join(SAMPLES, "python-fastapi-shop.zip"));
    await page.getByLabel("Project name").fill("Shop API e2e");
    await page.getByRole("button", { name: /Quick/ }).click();
    await page.getByTestId("start-analysis").click();
    await page.waitForURL(/\/projects\/[a-f0-9]{32}$/);
    // completes and switches from the progress view to the dashboard tabs
    await expect(page.getByRole("link", { name: "Context explorer" })).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText("API inventory")).toBeVisible();
    await expect(page.getByText(/openai_compatible · fake-local-model/)).toBeVisible();
    await expect(page.getByText("Core workflows")).toBeVisible();
    const url = page.url();

    // Context explorer: master document with all 32 sections, search, modular document
    await page.getByRole("link", { name: "Context explorer" }).click();
    await expect(page.getByRole("heading", { name: "Shop API e2e — Project Context" })).toBeVisible();
    await expect(page.locator(".md h2", { hasText: "32. Open Questions Requiring Developer Investigation" })).toBeVisible();
    await page.getByLabel("Search all documents").fill("get_current_user");
    await page.getByLabel("Search all documents").press("Enter");
    await expect(page.getByText(/matches for “get_current_user”/)).toBeVisible();
    await page.getByRole("button", { name: /07 · API Reference/ }).click();
    await expect(page.locator(".md h1").first()).toHaveText("API Reference");
    await expect(page.locator(".md")).toContainText("POST /api/orders");

    // Architecture explorer renders an interactive graph
    await page.goto(`${url}/architecture`);
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
    await page.locator(".react-flow__node").first().click();
    await expect(page.getByText(/Incoming \(/)).toBeVisible();
    await page.getByRole("tab", { name: "Database" }).click();
    await expect(page.locator(".react-flow__node", { hasText: "Order" }).first()).toBeVisible();

    // Issues
    await page.goto(`${url}/issues`);
    await expect(page.getByText("SQL built with string formatting")).toBeVisible();
    await page.getByText("SQL built with string formatting").click();
    await expect(page.getByText(/parameterised queries/)).toBeVisible();

    // Downloads
    const [master] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-master").click()]);
    expect(master.suggestedFilename()).toMatch(/CONTEXTFORGE_PROJECT_CONTEXT\.md$/);
    const text = fs.readFileSync((await master.path())!, "utf-8");
    expect(text).toContain("## 1. Project Overview");
    expect(text).not.toContain("a8F3kL9qZ2xV7mN4pR6tY1wE5uI0oPq"); // the sample's fake secret is redacted
    const [pkg] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-package").click()]);
    expect(pkg.suggestedFilename()).toMatch(/\.zip$/);
  });

  test("reset provider to deterministic mode", async ({ request }) => {
    const res = await request.put(`${API}/api/settings/provider`, { data: { provider: "none" } });
    expect(res.ok()).toBeTruthy();
  });
});
