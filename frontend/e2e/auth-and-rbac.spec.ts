import { expect, test } from "@playwright/test";
import { creds, signIn } from "./helpers";

test("wrong password shows a generic error, right password signs in", async ({ page }) => {
  const c = creds("admin");
  await page.goto("/finance");
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.getByLabel("Email").fill(c.email);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("Password").fill(c.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/finance$/);
  await expect(page.getByTestId("finance-summary")).toBeVisible();
});

test("employee: no Finance in the menu and the Finance page is refused", async ({ page }) => {
  await signIn(page, "employee");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "IT" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Finance" })).toHaveCount(0);
  await page.goto("/finance");
  await expect(page.getByTestId("forbidden")).toBeVisible();
  await page.goto("/documents");
  await expect(page.getByTestId("forbidden")).toBeVisible();
});

test("sign out returns to the sign-in page", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByTestId("user-menu").click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
});
