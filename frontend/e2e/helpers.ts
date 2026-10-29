import { expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Tests run from frontend/ (npm run e2e), so the repo data folder is one level up.
const DATA = path.resolve(process.cwd(), "..", "data");

// The phase gate runs against its own throwaway database and points this at that database's demo users.
const SEED_FILE = process.env.AGENTSMIND_SEED_CREDENTIALS || path.join(DATA, "seed_credentials.txt");

function rows(file: string): string[][] {
  const p = path.isAbsolute(file) ? file : path.join(DATA, file);
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, "utf8").split(/\r?\n/).filter(Boolean).map((l) => l.split("\t"));
}

/* Admin from data/local_credentials.txt (scripts/env_setup.py); demo users from data/seed_credentials.txt (scripts/seed.py). */
export function creds(who: "admin" | "hr" | "it" | "finance" | "employee"): { email: string; password: string } {
  if (who === "admin") {
    const r = rows("local_credentials.txt").find((x) => x[0] === "AgentsMind");
    if (!r) throw new Error("data/local_credentials.txt has no AgentsMind row. Run scripts/env_setup.py.");
    return { email: r[1], password: r[2] };
  }
  const r = rows(SEED_FILE).reverse().find((x) => x[1] === who);
  if (!r) throw new Error(`No ${who} user in ${SEED_FILE}. Run scripts/seed.py on a fresh database.`);
  return { email: r[0], password: r[2] };
}

export async function signIn(page: Page, who: Parameters<typeof creds>[0]) {
  const c = creds(who);
  await page.goto("/login");
  await page.getByLabel("Email").fill(c.email);
  await page.getByLabel("Password").fill(c.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

export async function ask(page: Page, text: string) {
  await page.goto("/assistant");
  await page.getByLabel("Message").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("assistant-message").last()).toBeVisible({ timeout: 45_000 });
}
