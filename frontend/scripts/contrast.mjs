// WCAG 2.1 contrast check for the design tokens in src/styles.css, light and dark.
// Body text pairs need 4.5:1; borders of form controls and focus rings need 3:1.
//   node scripts/contrast.mjs        (exit code 1 if any pair fails)
import fs from "node:fs";

const css = fs.readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
function block(selector) {
  const i = css.indexOf(selector + " {");
  const body = css.slice(i, css.indexOf("}", i));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));
}
const lum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

const TEXT = [
  ["fg", "bg"], ["fg", "surface"], ["fg", "surface-2"], ["muted", "bg"], ["muted", "surface"], ["muted", "surface-2"],
  ["primary", "surface"], ["primary", "bg"], ["primary", "primary-soft"], ["primary-fg", "primary"], ["primary-fg", "primary-hover"],
  ["success", "success-soft"], ["success", "surface"], ["warning", "warning-soft"], ["warning", "surface"],
  ["danger", "danger-soft"], ["danger", "surface"], ["fg", "success-soft"], ["fg", "warning-soft"], ["fg", "danger-soft"], ["fg", "primary-soft"],
];
const UI = [["border-strong", "surface"], ["focus", "surface"], ["focus", "bg"], ["warning", "surface"]];
let failed = 0;
for (const [name, sel] of [["light", ":root"], ["dark", '[data-theme="dark"]']]) {
  const t = block(sel);
  for (const [pairs, min] of [[TEXT, 4.5], [UI, 3]]) {
    for (const [f, b] of pairs) {
      const r = ratio(t[f], t[b]);
      const ok = r >= min;
      if (!ok) failed++;
      console.log(`${name.padEnd(5)} ${(f + " on " + b).padEnd(30)} ${r.toFixed(2).padStart(5)}  ${ok ? "ok" : "FAIL (needs " + min + ")"}`);
    }
  }
}
// Danger buttons: white text on --danger (light) and dark text on --danger (dark).
const dl = ratio("#ffffff", block(":root").danger), dd = ratio("#1a0a08", block('[data-theme="dark"]').danger);
console.log(`light white on danger button          ${dl.toFixed(2)}  ${dl >= 4.5 ? "ok" : "FAIL"}`);
console.log(`dark  #1a0a08 on danger button        ${dd.toFixed(2)}  ${dd >= 4.5 ? "ok" : "FAIL"}`);
if (dl < 4.5) failed++;
if (dd < 4.5) failed++;
console.log(failed ? `CONTRAST: ${failed} FAIL` : "CONTRAST: all pairs pass WCAG AA");
process.exit(failed ? 1 : 0);
