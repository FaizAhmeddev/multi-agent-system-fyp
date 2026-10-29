import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

const PAGES = ["/", "/assistant", "/approvals", "/hr", "/it", "/finance", "/documents", "/communications", "/admin", "/settings"];

async function audit(page: Page) {
  return page.evaluate(() => {
    const problems: string[] = [];
    const emoji = /\p{Extended_Pictographic}/u;
    if (emoji.test(document.body.innerText)) problems.push("emoji in visible text");
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const cs = getComputedStyle(el);
      if (cs.backgroundImage.includes("gradient")) problems.push(`gradient on <${el.tagName.toLowerCase()}>`);
      if (cs.backdropFilter && cs.backdropFilter !== "none") problems.push(`backdrop-filter on <${el.tagName.toLowerCase()}>`);
    }
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("input:not([type=hidden]), select, textarea"))) {
      const id = el.id;
      const labelled = el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || (id && document.querySelector(`label[for="${id}"]`)) || el.closest("label");
      if (!labelled) problems.push(`unlabelled ${el.tagName.toLowerCase()} ${id || el.getAttribute("name") || ""}`);
    }
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("button, a[href]"))) {
      const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || "").trim();
      if (!name) problems.push(`${el.tagName.toLowerCase()} without an accessible name`);
    }
    return problems;
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`design rules and labels, ${theme} theme`, async ({ page }) => {
    await signIn(page, "admin");
    await page.evaluate((t) => localStorage.setItem("agentsmind.theme", t), theme);
    for (const p of PAGES) {
      await page.goto(p);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.waitForLoadState("networkidle");
      expect(await audit(page), `page ${p}`).toEqual([]);
    }
  });
}

test("theme choice is remembered after reload", async ({ page }) => {
  await signIn(page, "admin");
  await page.getByTestId("theme-menu").click();
  await page.getByRole("menuitem", { name: /Dark/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
