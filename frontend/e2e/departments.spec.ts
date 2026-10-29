import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test("IT: an employee raises a complaint and gets the ticket number and confirmation page", async ({ page, context }) => {
  await signIn(page, "employee");
  await page.goto("/it");
  await page.getByRole("button", { name: "New complaint" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Department").selectOption("Sales");
  await dlg.getByLabel("What is wrong?").fill("My laptop cannot join the office Wi-Fi since this morning (e2e).");
  await page.getByRole("button", { name: "Submit complaint" }).click();
  const done = page.getByTestId("ticket-created");
  await expect(done).toContainText(/ITK-\d{6}/);
  const [popup] = await Promise.all([context.waitForEvent("page"), done.getByRole("link", { name: /confirmation/ }).click()]);
  await expect(popup.getByText("Complaint submitted")).toBeVisible();
});

test("Finance: add a person, then delete only after typing the full name", async ({ page }) => {
  await signIn(page, "finance");
  await page.goto("/finance");
  await page.getByRole("button", { name: "Add person" }).click();
  const dlg = page.getByRole("dialog");
  const name = `E2e Person ${Date.now() % 100000}`;
  await dlg.getByLabel("Full name").fill(name);
  await dlg.getByLabel("Email").fill(`e2e.${Date.now()}@example.com`);
  await dlg.getByLabel("Department").selectOption("Sales");
  await dlg.getByLabel("Job title").fill("Account Manager");
  await dlg.getByLabel("Monthly salary").fill("150000");
  await dlg.getByLabel("Start date").fill("2026-12-01");
  await dlg.getByRole("button", { name: "Add person" }).click();
  await expect(dlg).toHaveCount(0);
  await page.getByLabel("Search").fill(name);
  await expect(page.getByRole("table", { name: "People records" })).toContainText(name);
  await page.getByRole("button", { name: `Delete ${name}` }).click();
  const del = page.getByRole("button", { name: "Delete permanently" });
  await expect(del).toBeDisabled();
  await page.getByRole("dialog").getByLabel(`Type ${name} to confirm`).fill(name);
  await del.click();
  await expect(page.getByTestId("toast").last()).toContainText("deleted");
});

test("HR: screening fills the board and flags the hostile CV for review", async ({ page }) => {
  await signIn(page, "hr");
  await page.goto("/hr");
  await page.getByRole("button", { name: "Screen CVs" }).click();
  const board = page.getByTestId("candidates-board");
  const hostile = board.getByTestId("candidate-card").filter({ hasText: "Alex Example" });
  await expect(hostile).toContainText("Needs review", { timeout: 45_000 });
  await expect(board).toContainText("Sara Khan");
});

test("Documents: summary is labeled Simulated without a model", async ({ page }) => {
  await signIn(page, "hr");
  await page.goto("/documents");
  await page.getByRole("button", { name: /Leave_Policy/ }).click();
  await page.getByRole("button", { name: "Summarize" }).click();
  const s = page.getByTestId("doc-summary");
  await expect(s).toContainText("20 working days");
  await expect(s.getByTestId("simulated")).toBeVisible();
});

test("Communications: the hostile message is marked suspicious", async ({ page }) => {
  await signIn(page, "employee");
  await page.goto("/communications");
  await expect(page.getByTestId("inbox")).toContainText("Suspicious");
});
