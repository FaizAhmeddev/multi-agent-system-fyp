# Office Automation Pro brand assets

`office-automation-original.png` is the user-supplied, unmodified transparent PNG.
`office-automation-logo.png` crops transparent outer whitespace, preserving the
original pixels, lettering and colored OA artwork. `office-automation-icon.png`
isolates the original OA mark. The PNG/ICO favicons center that mark on #F8FAFF for
legibility in browser tabs with either appearance.

The shared `ui/branding.py` helper embeds the full-resolution wordmark locally;
there are no external asset requests. Login, registration and password reset share
the auth header; Dashboard and all other workspace pages share the sidebar header.
Both headers have transparent backgrounds. `office-automation-logo-dark.png`
changes only dark wordmark pixels to #F8FAFF; the colored OA mark and PRO badge
retain their original colors. Light mode uses the original dark wordmark.
The source asset is unchanged, and no whole-logo inversion or filter is applied.
Responsive CSS retains the aspect ratio and constrains the artwork to its container.
