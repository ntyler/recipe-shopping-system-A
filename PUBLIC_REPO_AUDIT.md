# Public Repository Audit

Date: 2026-07-01

Scope: `D:\GitHub\recipe-shopping-system-A`

Purpose: prepare this repository for a public GitHub release and LinkedIn portfolio use.

## Executive Summary

This repository contained tracked runtime data, generated assets, screenshots, browser-profile artifacts, local admin audit logs, and hardcoded project-specific Firebase web configuration. Those items are not appropriate for a public portfolio repository.

Actions taken:

- Removed hardcoded Firebase web config values from tracked source.
- Moved staff/admin identity defaults to environment-driven configuration.
- Replaced personal/test email addresses and machine-specific host/IP examples in tracked source, docs, and tests.
- Added `.env.example` with placeholder-only setup values.
- Rebuilt `.gitignore` to block future local secrets, user data, generated files, browser profiles, PDFs, logs, and databases.
- Removed generated/private artifacts from Git tracking with `git rm --cached`; the local files still exist on disk.

Important: `git rm --cached` removes files from the next commit, but it does not erase prior Git history. If this repository was ever pushed to a remote with the removed files present, rewrite history before making it public and rotate any affected secrets.

## Scan Limitations

- `gitleaks`, `trufflehog`, and `detect-secrets` were not installed locally, so this audit used repository inventory, `git grep`, `rg`, and targeted pattern scans.
- The Codex Security delegated-worker preflight was incomplete because no delegated workers were available in this session. The audit was completed in the parent agent instead.
- Binary files and PDFs were identified by path/type and removed from tracking rather than exhaustively content-inspected.

## Risky Files And Actions

| File or file set | Risk | Action |
|---|---|---|
| `.env` | Local secrets file. It contained local API/config values during the audit. | Already ignored; not tracked. Keep private and never commit. |
| `local_env.bat` | Local startup secrets/settings, including API/model/email configuration. | Already ignored; not tracked. Keep private and never commit. |
| `PushShoppingList/services/firebase_auth_service.py` | Contained a real Firebase web app config in source. | Replaced defaults with empty env-backed values. Documented required Firebase vars in `.env.example`. |
| `PushShoppingList/static/js/firebase-auth.js` | Contained the same real Firebase web config in frontend JavaScript. | Replaced local fallback values with blanks; page config now comes from Flask/env values. |
| `PushShoppingList/services/user_account_service.py` | Contained a personal admin email in tracked code. | Replaced with `SHOPPING_APP_ADMIN_EMAIL` and `SHOPPING_APP_SUPPORT_ADMIN_EMAILS` config. |
| `PushShoppingList/static/js/app.js` | Contained a personal support-admin email in frontend JavaScript. | Replaced with page-provided `supportPublicConfig`. |
| `PushShoppingList/routes/main_routes.py` and `PushShoppingList/templates/index.html` | Needed safe support config delivery to frontend JavaScript. | Added a JSON config script populated from environment-backed server values. |
| `PushShoppingList/templates/landing.html` | Beta form used a personal email address. | Replaced with project support email. |
| `README.md` | Included personal admin email, local LAN IP, real Tailscale hostname, and Firebase-default wording. | Replaced with neutral examples/placeholders and documented that Firebase config must be supplied locally. |
| `phone scripts/start_shopping_app.py` | Included local Tailscale hosts, Windows username, repo path, and public app URL. | Replaced with environment-configurable placeholders. |
| `phone scripts/README.md` | Included local Tailscale hosts, LAN IP, username, and public app URL examples. | Replaced with placeholders. |
| `start_app.bat` | Hardcoded local repo path. | Changed to start from the batch file directory via `%~dp0`. |
| `tests/test_admin_support_service.py` | Used real-looking personal emails in test fixtures. | Replaced with `admin@example.com` / `user@example.com`. |
| `tests/test_feedback_mark_read_route.py` | Used real-looking personal emails in test fixtures. | Replaced with placeholder emails. |
| `tests/test_openai_model_service.py` | Used a real-looking personal admin email in test fixtures. | Replaced with placeholder email. |
| `tests/test_pdf_share_routes.py` | Used a real-looking personal admin email in test fixtures. | Replaced with placeholder email. |
| `tests/test_store_request_feedback.py` | Used a real-looking personal admin email in test fixtures. | Replaced with placeholder email. |
| `tests/test_two_factor_recovery_account_specific.py` | Used real-looking personal emails in test fixtures. | Replaced with placeholder emails. |
| `tests/test_user_account_layout.py` | Expected the old hardcoded frontend support-admin list. | Updated to assert the new config-driven behavior. |
| `PushShoppingList/admin_support_audit.json` | Local admin-support access log with private account identifiers. | Removed from Git tracking; ignored going forward. |
| `PushShoppingList/device_status_events.json` | Local device/user-agent/session status metadata. | Removed from Git tracking; ignored going forward. |
| `PushShoppingList/feedback.json` | Local user feedback data with private account identifiers/comments. | Removed from Git tracking; ignored going forward. |
| `PushShoppingList/openai_model_list_cache.json` | Local/admin model cache data. | Removed from Git tracking; ignored going forward. |
| `PushShoppingList/openai_model_overrides.json` | Local/admin model override settings. | Removed from Git tracking; ignored going forward. |
| `PushShoppingList/openai_model_recommendation_cache.json` | Local/admin model recommendation cache. | Removed from Git tracking; ignored going forward. |
| `PushShoppingList/services/recipe-extractor/data/**` | 377 tracked runtime files, including extracted recipes, uploaded-file metadata, generated PDFs/docs/images, product scrape output, raw HTML/text, store/address-derived state, and local paths. | Removed from Git tracking; ignored going forward. The app regenerates/defaults runtime data as needed. |
| `PushShoppingList/static/generated/**` | 162 tracked generated image files, including AI/generated recipe-step images. | Removed from Git tracking; ignored going forward. |
| `PushShoppingList/downloaded_recipe_html/https_www_forkinthekitchen_com_chocolate_chip_muffins.html` | Cached third-party recipe HTML. | Removed from Git tracking; ignored going forward. |
| `output/playwright/menu-import-guest.png` | Generated browser screenshot from local testing. | Removed from Git tracking; ignored going forward. |
| `output/playwright/menu-import-page.png` | Generated browser screenshot from local testing. | Removed from Git tracking; ignored going forward. |
| `tmp_selenium_profile/Default/Preferences` | Browser profile state. May contain local browsing/session metadata. | Removed from Git tracking; ignored going forward. |
| `tmp_selenium_profile/First Run` | Browser profile marker. | Removed from Git tracking; ignored going forward. |
| `tmp_selenium_profile/Local State` | Browser local state. May contain profile/cache/session metadata. | Removed from Git tracking; ignored going forward. |

## Removed From Git Tracking

The following file sets were staged as deletions from Git tracking only. They were not deleted from the local working directory:

- `PushShoppingList/services/recipe-extractor/data/**` - 377 files
- `PushShoppingList/static/generated/**` - 162 files
- `PushShoppingList/downloaded_recipe_html/**` - 1 file
- `output/playwright/**` - 2 files
- `tmp_selenium_profile/**` - 3 files
- Local JSON runtime/admin files - 6 files

Run this to see every staged untracked-removal path:

```powershell
git diff --cached --name-only --diff-filter=D
```

## Files To Manually Review Before Publishing

- `.env` and `local_env.bat`: confirm they remain ignored and never stage them.
- `PushShoppingList/user_data/`: local user workspaces, PDFs, menus, generated data, and uploads should stay private.
- `PushShoppingList/services/recipe-extractor/data/`: confirm no file from this runtime directory is intentionally needed as a public fixture.
- `PushShoppingList/static/generated/`: keep generated/AI images out of the public repo unless you intentionally choose sanitized demo assets.
- `PushShoppingList/static/uploads/`: verify only `.gitkeep` is tracked.
- `PushShoppingList/admin_support_audit.json`, `PushShoppingList/feedback.json`, and `PushShoppingList/device_status_events.json`: keep private.
- Firebase Console: confirm authorized domains, test accounts, and service accounts are safe for public exposure.
- Cloudflare R2: confirm bucket names, public domains, keys, and PDF object policies are safe.
- README domain references such as `app.recipeshoppinglist.com` and `support@recipeshoppinglist.com`: keep only if those are intentionally public project identifiers.
- Git history: if the removed files or Firebase web config were ever pushed, purge them from history and rotate relevant credentials/config.

## Verification Run During Audit

The following checks were run after cleanup:

- Tracked risky path scan: no remaining tracked matches for private runtime directories, local DB/log/PDF extensions, Selenium profiles, or Playwright output.
- Personal/local marker scan: no tracked matches for the personal Gmail addresses, local LAN IP, real Tailscale hostname, or local repo path markers that were found earlier.
- Ignore check: `.env`, `local_env.bat`, `PushShoppingList/user_data/`, `PushShoppingList/services/recipe-extractor/data/`, `tmp_selenium_profile/`, `output/playwright/`, and `PushShoppingList/static/generated/` are ignored.

Expected false positives remain in source/docs/tests for environment variable names and placeholder examples, such as `OPENAI_API_KEY`, `R2_SECRET_ACCESS_KEY`, and `support@recipeshoppinglist.com`.

## Recommended Next Steps

1. Review `git diff --cached --name-only --diff-filter=D` before committing to confirm all staged removals are intentional.
2. Run the verification commands in the final assistant response.
3. If this repository has ever been pushed with the removed files, run a history-cleaning tool such as `git filter-repo` or BFG Repo-Cleaner before making it public.
4. Rotate any Firebase, OpenAI, Cloudflare, SMTP, or other credentials that may have been committed or pushed in prior history.
