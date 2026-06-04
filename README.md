# Recipe Shopping System

Self-hosted recipe-to-shopping-list automation platform with recipe extraction, ingredient parsing, shopping list management, store selection, product lookup, ChatGPT-assisted best-product selection, food-rule review markers, Firebase-backed user accounts, Cloudflare R2 recipe PDF sharing, per-user ntfy notifications, and a mobile-friendly Flask UI.

## Requirements

Use **Python 3.11** for this project. The included `start_app.bat` runs the app with:

```bat
py -3.11 app.py
```

You also need:

- Google Chrome installed, for Selenium and browser fallback recipe fetching
- A working internet connection for recipe downloads, OpenAI API calls, Firebase Authentication, Cloudflare R2 uploads, product lookups, and ntfy notifications
- Optional but recommended: Tailscale, ZeroTier, WireGuard, or another mesh/VPN tool if you want to use the app from your phone
- Optional: Cloudflare Tunnel, Tailscale Funnel, ngrok, or another HTTPS tunnel if you want a public HTTPS URL

## Python 3.11 Libraries

Install the Python dependencies from `requirements.txt`:

```powershell
py -3.11 -m pip install -r requirements.txt
```

Core libraries used by the project:

- `Flask`: web app and routes
- `requests`: recipe downloads, ntfy notifications, and HTTP calls
- `beautifulsoup4`: recipe HTML parsing
- `openai`: recipe extraction, sorting, and quantity scaling
- `Pillow`: product image conversion for embedded Base64 image data
- `selenium`: browser fallback for blocked recipe pages
- `undetected-chromedriver`: Chrome fallback for sites that return 403 to direct downloads
- `webdriver-manager`: ChromeDriver helper/fallback support
- `boto3`: Cloudflare R2 PDF uploads
- `firebase-admin`: backend verification for Firebase Authentication ID tokens

## Environment Variables

Set these before starting the app.

Required for recipe extraction and AI sorting:

```powershell
$env:OPENAI_API_KEY="your_openai_api_key_here"
```

Optional ntfy topic for phone/computer extraction notifications:

```powershell
$env:NTFY_TOPIC="your-private-shopping-list-topic"
```

Optional SMTP settings for account verification, password reset, two-factor disable verification, and account deletion verification emails:

```powershell
$env:SHOPPING_APP_SMTP_HOST="smtp.gmail.com"
$env:SHOPPING_APP_SMTP_PORT="587"
$env:SHOPPING_APP_SMTP_USERNAME="your_email@gmail.com"
$env:SHOPPING_APP_SMTP_PASSWORD="your_email_app_password"
$env:SHOPPING_APP_SMTP_FROM_EMAIL="your_email@gmail.com"
$env:SHOPPING_APP_SMTP_FROM_NAME="Recipe Shopping System"
$env:SHOPPING_APP_SMTP_USE_TLS="1"
$env:SHOPPING_APP_PASSWORD_RESET_BASE_URL="https://app.recipeshoppinglist.com"
$env:SHOPPING_APP_ACCOUNT_LINK_BASE_URL="https://app.recipeshoppinglist.com"
```

When using `start_app.bat`, place the same values in an untracked `local_env.bat` file. A safe template is included at `local_env.example.bat`, and `start_app.bat` loads `local_env.bat` before starting Flask.

Optional Firebase Authentication settings:

```powershell
$env:FIREBASE_API_KEY="your_web_api_key"
$env:FIREBASE_AUTH_DOMAIN="your-project.firebaseapp.com"
$env:FIREBASE_PROJECT_ID="your-project-id"
$env:FIREBASE_STORAGE_BUCKET="your-project.firebasestorage.app"
$env:FIREBASE_MESSAGING_SENDER_ID="your_sender_id"
$env:FIREBASE_APP_ID="your_web_app_id"
$env:FIREBASE_MEASUREMENT_ID="your_measurement_id"
```

The app has local-development Firebase web defaults for the Recipe Shopping App project. For backend verification, set one of these and keep the service account file untracked:

For the current Recipe Shopping App Firebase project, the frontend and backend should both use measurement ID `G-J44GKNGRDY`.

```powershell
$env:FIREBASE_SERVICE_ACCOUNT_PATH="C:\path\to\firebase-service-account.json"
```

or:

```powershell
$env:FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account", "...":"..."}'
```

Firebase Console setup:

1. Confirm Email/Password is enabled under Authentication > Sign-in method.
2. Confirm Google is enabled under Authentication > Sign-in method.
3. Open Authentication > Settings > Authorized domains.
4. Add `localhost`, `127.0.0.1`, `app.recipeshoppinglist.com`, and `recipeshoppinglist.com`.
5. Add a temporary tunnel hostname only while testing with a temporary Cloudflare Tunnel or another temporary HTTPS tunnel.
6. Do not include `https://` when adding authorized domains.

Optional Cloudflare R2 settings for public recipe PDF links:

```powershell
$env:R2_ACCOUNT_ID="your_account_id"
$env:R2_ENDPOINT="https://your_account_id.r2.cloudflarestorage.com"
$env:R2_ACCESS_KEY_ID="your_r2_access_key"
$env:R2_SECRET_ACCESS_KEY="your_r2_secret_key"
$env:R2_BUCKET_NAME="your_bucket"
$env:R2_PUBLIC_BASE_URL="https://your_public_r2_domain"
$env:DELETE_LOCAL_PDF_AFTER_UPLOAD="0"
```

Public PDF links are built as `R2_PUBLIC_BASE_URL + "/" + r2_object_key`. Do not use localhost, 127.0.0.1, or trycloudflare URLs as public PDF share links.

Set `DELETE_LOCAL_PDF_AFTER_UPLOAD=1` only if you want generated local PDFs removed after a successful Cloudflare R2 upload.

Optional recipe-fetch controls:

```powershell
$env:DISABLE_BROWSER_RECIPE_FETCH="1"
$env:DISABLE_RECIPE_HTML_CACHE_FALLBACK="1"
$env:DISABLE_RECIPE_PDF_ARCHIVE="1"
$env:FORCE_OPENAI_RECIPE_EXTRACTION="1"
```

Optional app and product-lookup controls:

```powershell
$env:SHOPPING_APP_PORT="5083"
$env:PRODUCT_SEARCH_WORKERS="2"
$env:PRODUCT_DETAIL_LIMIT_PER_STORE="4"
$env:PRODUCT_AI_ANALYSIS_LIMIT_PER_STORE="2"
$env:PRODUCT_FINAL_SELECTION_CANDIDATES="96"
$env:PRODUCT_AI_BROWSER_WAIT_SECONDS="4"
```

Notes:

- Leave `DISABLE_BROWSER_RECIPE_FETCH` unset unless you do not want Selenium/Chrome fallback.
- Leave `DISABLE_RECIPE_HTML_CACHE_FALLBACK` unset if you want the app to reuse cached recipe HTML when a live page fails.
- Leave `DISABLE_RECIPE_PDF_ARCHIVE` unset if you want each extracted recipe page saved as a PDF for later review.
- Set `FORCE_OPENAI_RECIPE_EXTRACTION=1` only when you want the OpenAI extractor used even if recipe-card HTML already has enough structured data.
- Leave `SHOPPING_APP_PORT` unset when running `py -3.11 app.py` directly and you want the default Flask port `5000`. The included `start_app.bat` currently sets `SHOPPING_APP_PORT=5083`.
- Set `SHOPPING_APP_PASSWORD_RESET_BASE_URL` to the address users should open from password reset and two-factor disable verification emails, such as your LAN, Tailscale, or public HTTPS URL. If unset, reset emails use the current request host.
- Set `SHOPPING_APP_ACCOUNT_LINK_BASE_URL` to the address users should open from account verification and account deletion emails. If unset, account links fall back to `SHOPPING_APP_PASSWORD_RESET_BASE_URL` or the current request host.
- Product lookup uses `OPENAI_API_KEY` for fully loaded product-page analysis and final best-product selection. If no key is set, the app still parses product candidates but skips ChatGPT product analysis.
- Product image embedding is enabled by default. Set `DISABLE_PRODUCT_IMAGE_EMBEDDING=1` to skip downloading images into `embedded_image_base64`.
- Full Base64 image strings are stored on candidates but omitted from ChatGPT prompts by default to keep prompts usable. Set `PRODUCT_PROMPT_INCLUDE_EMBEDDED_IMAGES=1` only if you really want those large strings sent to the API.

On Windows, you can make variables persistent with:

```powershell
setx OPENAI_API_KEY "your_openai_api_key_here"
setx NTFY_TOPIC "your-private-shopping-list-topic"
```

Open a new terminal after using `setx`.

## Running The App

From the repo root:

```powershell
py -3.11 app.py
```

Then open:

```text
http://127.0.0.1:5000
```

That direct command uses the default port `5000` unless `SHOPPING_APP_PORT` is set.

Or use:

```powershell
.\start_app.bat
```

The included launcher currently sets `SHOPPING_APP_PORT=5083`, so it opens:

```text
http://127.0.0.1:5083
```

The app also listens on your LAN address, so another device on the same Wi-Fi can open:

```text
http://<computer-lan-ip>:5000
```

If you use `start_app.bat`, replace `5000` with `5083`.

Example from the current setup:

```text
http://192.168.68.62:5083
```

If a Cloudflare Tunnel is pointed at the local Flask port, the public app URL is:

```text
https://app.recipeshoppinglist.com/
```

Use the Cloudflare Tunnel URL for the app UI only. Recipe PDF share links should point directly to Cloudflare R2, not to the app tunnel.

## User Accounts And Security

The User Account section uses Firebase Authentication on the frontend and Flask session verification on the backend.

- Firebase Web SDK is loaded with `<script type="module">` imports from `gstatic`; do not use npm or Firebase Hosting for this Flask app.
- Supported Firebase providers are Email/Password and Google sign-in.
- Backend session verification uses `/auth/firebase-login`, `/auth/logout`, and `/auth/session`.
- The UI shows `Connected via Firebase Authentication` only after backend verification succeeds.
- Browser refreshes should keep the Firebase session and Flask account state in sync.
- `ntylerbert@gmail.com` is treated as `Admin`; other signed-in users are `User` unless code or stored user data changes.
- The signed-in account card stays focused on profile photo, name, email, role, email verification status, created date, and last sign-in date.

Account Menu items:

- `Account Settings`: edit first name, last name, username, email, and uploaded logo/avatar.
- `Change Password`: sends the Firebase password reset/change flow for Firebase users.
- `Verify Email` or `Email Verified`: verified accounts show a disabled `Email Verified` item instead of an action button.
- `Two-Factor Authentication`: opens the authenticator app and backup-code panel.
- `Push Notifications`: opens notification status, devices, and preferences.
- `Delete Account`: sends a one-time email verification link before deleting the account.
- `Sign Out`: signs out of Firebase and clears the Flask session.

Profile photos use the uploaded logo/avatar first. If the uploaded logo is removed, the account falls back to the Firebase/Google profile photo when available, then to the generated initial avatar.

Two-factor authentication is account-specific:

- Setup uses an authenticator app secret, QR code when available, and one-time backup codes.
- First-time setup asks the user to confirm the new authenticator code once with a setup-specific confirmation screen.
- Sign-in can remember the browser for 30 days.
- Backup-code regeneration requires an authenticator code or backup code.
- Normal disable requires an authenticator code or backup code.
- If the user lost the authenticator app and backup codes, the recovery option sends a one-time disable verification link to the account email.
- Email disable links are tied to the account that requested the email. Opening the link should not switch to another signed-in account.
- Account action pages for password reset, two-factor disable verification, and account deletion should remain visible until the user completes the action or clicks cancel.

## Recipe PDF Sharing

Recipe PDFs are cached in Cloudflare R2 so public PDF access does not stream large files through Flask or through a Cloudflare Tunnel.

For each recipe URL, the app builds a stable PDF filename and R2 object key:

```text
source URL: https://www.forkinthekitchen.com/vegetarian-green-enchiladas-verde/
object key: recipe-pdfs/forkinthekitchen_com_vegetarian-green-enchiladas-verde.pdf
```

Important behavior:

- `Create Recipe PDF` generates the PDF, uploads it to Cloudflare R2 when R2 is configured, saves metadata, and returns the Cloudflare public URL.
- `GET /recipe_pdf_link?url=<recipe_url>` returns JSON with `success`, `cached`, `public_url`, `r2_object_key`, `uploaded_at`, `cloud_status`, and timing data.
- `GET /recipe_archive_pdf?url=<recipe_url>` redirects to the Cloudflare R2 public URL when one exists. If no cached R2 URL exists, it generates, uploads, saves metadata, then redirects.
- Local PDF download through Flask is reserved for explicit admin download/local fallback behavior.
- `Open PDF`, `Copy PDF Link`, and shared PDF controls should use R2 public URLs. Do not copy or display `localhost`, `127.0.0.1`, or `trycloudflare.com` URLs as PDF share links.
- R2 metadata is saved inside each recipe output JSON under the recipe `pdf` metadata, including `r2_object_key`, `r2_public_url`, `uploaded_at`, and `cloud_status`.

The first PDF generation may take time. Later requests should be fast because they redirect to the cached Cloudflare R2 static URL.

## Best Product Lookup

The **Grab Best Products** button searches the activated stores near the saved Full Address for every shopping-list item. The current workflow is:

1. The Planner Agent builds item/store searches from the shopping list and saved Full Address.
2. The Store Resolution Agent resolves the nearest pickup-oriented location for each activated store.
3. Browser Worker Agents run in parallel with `ThreadPoolExecutor`, open the real grocery search/category pages with Selenium/undetected Chrome, apply the saved address context, select the nearest pickup-oriented store when the page exposes a store selector, and scroll until lazy-loaded product content stops changing.
4. Before extracting products, the browser worker verifies localized store-session proof such as a selected-store banner, store ZIP/address, pickup/delivery indicator, or store/session ID. If localization cannot be proven, it stops and records a failure instead of ranking generic catalog inventory.
5. The Product Extraction/Normalization Agent uses a generic browser snapshot workflow instead of store-specific scraper scripts. It saves the fully rendered page HTML under `data/raw/product_pages/`, plus readable `_TEXT.txt`, cleaned `_PROMPT_PREVIEW.html`, and `_PRODUCTS.html` snapshots for debugging. It extracts visible product-related HTML/content with broad DOM heuristics, removes scripts/styles/tracking markup, and normalizes store name, store address, product name, brand, size/count, price, unit price, stock status, direct product URL, image URL, cleaned raw product-card HTML snippet, and embedded image Base64 where possible.
6. Shortlisted candidates are opened on their full product detail pages for deeper evidence.
7. The Validation Layer rejects irrelevant, unavailable, search-page-only, or rule-failing products while saving rejection reasons.
8. The Ranking Agent sends the saved rules, cleaned rendered product HTML, generic product blocks, and proof of store selection to ChatGPT when `OPENAI_API_KEY` is available. ChatGPT does not browse store websites; it identifies product candidates and ranks the supplied page/card data into best product, best value pick, best premium pick, valid alternatives, and rejected products with rejection reasons and confidence scores.
9. Results are saved with the best product, valid alternatives, rejected products, rejection reasons, localization proof, scoring metadata, manual selection metadata, and store/ingredient metadata.

For eggs, the built-in ranking prefers standard shell egg cartons, 12-count or larger cartons, availability, nearby stores, and lower price per egg. It avoids unrelated egg products such as liquid eggs, egg whites only, boiled eggs, egg bites, and plant-based egg substitutes when possible.

The UI shows:

- `Picked`: the overall strict-rule product selected across stores.
- `Store Pick`: the best direct product found for that store. If the product does not satisfy strict rules, it can still be shown as the store's best available candidate while preserving the rule issue in the saved choice.
- Each enabled store under each ingredient, with the store's best product price beside it.
- Product names as direct links to product pages, not search pages, whenever a direct product URL is available.
- An `Alternatives` button beside each store that shows valid alternatives and rejected products with reasons.
- A `Prompt` button on store picks and picked products so you can inspect the extracted-card prompt sent to the ChatGPT API. Full prompts are stored under `raw/product_prompts/` and loaded only when requested.
- Manual alternative selections persist as `selected_by_user` with `selected_at`.

The **Test Grab** button is an isolated diagnostic run backed by `PushShoppingList/scripts/test_grab_aldi_eggs.py`. It does not update the normal saved product choices. When clicked, it prompts for an ingredient, searches only ALDI from the saved current Full Address, requires localized store-session proof before product extraction, uses an ingredient-aware ranking prompt, runs Selenium/Chrome headlessly by default, and saves the last diagnostic payload to:

```text
PushShoppingList/services/recipe-extractor/data/test_grab_result.json
```

You can run the same diagnostic directly:

```powershell
py -3.11 PushShoppingList\scripts\test_grab_aldi_eggs.py
```

Set `TEST_GRAB_VISIBLE=1` only when you want to watch Chrome. When visible mode is enabled, `TEST_GRAB_VISUAL_PAUSE_SECONDS` slows each step and `TEST_GRAB_VISUAL_HOLD_SECONDS` keeps the browser open longer before it closes.

For direct script runs, set `TEST_GRAB_INGREDIENT` to search something other than `eggs`.

Product choice state is saved in:

```text
PushShoppingList/services/recipe-extractor/data/product_choices.json
PushShoppingList/services/recipe-extractor/data/product_results.json
```

## Tailscale Access

The Flask app listens on all network interfaces:

```python
host="0.0.0.0"
port=int(os.getenv("SHOPPING_APP_PORT", "5000"))
```

### Tailnet-Only Access

Use Tailscale Serve when you only want devices in your Tailscale tailnet to reach the app:

```powershell
tailscale serve --bg http://127.0.0.1:5083
tailscale serve status
```

Current tailnet URL:

```text
https://desktop-in7s09s.tail906b20.ts.net/
```

Turn off tailnet-only Serve:

```powershell
tailscale serve --https=443 off
```

### Public Internet Access

Use Tailscale Funnel when you want the Flask app reachable from outside your tailnet:

```powershell
tailscale funnel --bg --yes http://127.0.0.1:5083
tailscale funnel status
```

Current public Funnel URL:

```text
https://desktop-in7s09s.tail906b20.ts.net/
```

Turn off public Funnel access:

```powershell
tailscale funnel --https=443 off
```

Important: Funnel exposes the app on the public internet. Do not leave Funnel running unless you are comfortable with anyone who has the URL reaching the app.

### Private Mesh/VPN Access

For phone access without making the app public, put your computer and phone on the same private mesh network.

Recommended setup:

1. Install Tailscale, ZeroTier, or WireGuard on the computer running Flask.
2. Install the same mesh/VPN app on your phone.
3. Join both devices to the same private network.
4. Start the Flask app on the computer.
5. On the phone, open:

```text
http://<computer-mesh-ip>:5000
```

If you use the included launcher, use port `5083` instead:

```text
http://<computer-mesh-ip>:5083
```

Examples:

```text
http://100.x.y.z:5083
http://10.x.y.z:5083
```

## HTTPS / Secure Page Access

Phone GPS/geolocation requires a secure browser origin. `http://<ip>:5000` or `http://<ip>:5083` will show as **Not Secure**, so mobile browsers may block `Use My Location`.

Tailscale Serve and Tailscale Funnel provide HTTPS at:

```text
https://desktop-in7s09s.tail906b20.ts.net/
```

Quick test with Flask's temporary self-signed certificate:

```powershell
$env:SHOPPING_APP_SSL_ADHOC="1"
$env:SHOPPING_APP_PORT="5083"
py -3.11 app.py
```

Then open:

```text
https://<computer-ip>:5083
```

Your browser will warn because the certificate is self-signed. For the most reliable phone experience, use one of these:

- A trusted local certificate, then start with:

```powershell
$env:SHOPPING_APP_SSL_CERT="C:\path\to\cert.pem"
$env:SHOPPING_APP_SSL_KEY="C:\path\to\key.pem"
py -3.11 app.py
```

- A trusted HTTPS tunnel such as Tailscale Funnel, Cloudflare Tunnel, or ngrok pointed at `http://127.0.0.1:5000`.
- For the included `start_app.bat`, point the tunnel at `http://127.0.0.1:5083`.

Do not expose this app publicly unless you add authentication, keep the tunnel private, or only run public access temporarily.

If the phone cannot connect:

- Confirm both devices are online in the mesh/VPN app.
- Allow Python/Flask through Windows Firewall for private networks.
- Make sure nothing else is already using the port you started Flask on, usually `5000` for direct runs or `5083` for `start_app.bat`.
- Use the mesh IP, not `127.0.0.1`; `127.0.0.1` only works on the same device.

## ntfy Notifications

The app can send extraction started/complete/cancelled notifications and account preference test notifications through `ntfy.sh`.

Signed-in users get their own generated topic stored with their account. Open `Account Menu > Push Notifications` to enable/disable notifications, open the topic, copy the topic link, send a test notification, and manage preferences.

Notification preferences currently include:

- Recipe Import Complete
- Recipe PDF Generated
- Cloudflare Upload Complete
- Store Search Complete
- Shopping List Updated
- Feedback Response
- Security Alerts

Device display is ready for multi-device notification management and currently shows devices such as Windows PC, iPhone, and Browser when available.

`NTFY_TOPIC` is still useful as a fallback/global topic for guest activity or code paths that do not have a signed-in user topic.

Example:

```powershell
$env:NTFY_TOPIC="nathaniel-shopping-list-12345"
```

Notifications are best treated as convenience alerts. The actual UI sync comes from the Flask page polling the extraction progress file.

## Firebase Auth Manual Test Checklist

1. Confirm Email/Password is enabled in Firebase Console.
2. Confirm Google is enabled in Firebase Console.
3. Confirm `localhost`, `127.0.0.1`, `app.recipeshoppinglist.com`, and `recipeshoppinglist.com` are authorized domains.
4. Start the Flask app.
5. Open the app signed out.
6. Confirm no Firebase setup/debug banners appear.
7. Create an account with email/password.
8. Confirm the backend Flask session is created.
9. Sign out.
10. Sign in with email/password.
11. Test forgot password.
12. Test Google sign-in.
13. Sign in as `ntylerbert@gmail.com` and confirm the Admin role and Admin access enabled badge.
14. Sign in as another user and confirm the User role.
15. Confirm `Connected via Firebase Authentication` appears only after backend session verification succeeds.
16. Confirm email verification status is shown. If the email is already verified, the Account Menu item should read `Email Verified` and be disabled.
17. Confirm Account Menu contains Account Settings, Change Password, Verify Email or Email Verified, Two-Factor Authentication, Push Notifications, Delete Account, and Sign Out.
18. Confirm Account Settings can remove an uploaded logo/avatar and falls back to the Firebase/Google profile photo when available.
19. Confirm normal two-factor disable requires an authenticator code or backup code.
20. Confirm two-factor authentication is account-specific. A disable verification link emailed to one user should disable only that user's two-factor settings.
21. Confirm account action pages for password reset, two-factor disable verification, and account deletion do not collapse into a blank screen before the user completes or cancels the action.
22. Confirm Push Notifications lives inside Account Menu and can enable, disable, send a test notification, and update preferences.
23. Confirm signed-out users cannot manage protected sections.
24. Confirm a signed-in admin user can create and upload a PDF to Cloudflare R2.
25. Confirm Copy PDF Link copies an R2 URL.
26. Confirm the copied PDF link does not contain localhost, 127.0.0.1, trycloudflare, or the app tunnel hostname.
27. Confirm `/recipe_archive_pdf?url=<recipe_url>` redirects to the R2 public URL after the first generated upload.
28. Confirm secrets, service account JSON files, and generated PDFs are not shown in `git status`.

## Important Data Files

Most app state is stored under:

```text
PushShoppingList/services/recipe-extractor/data/
```

Account state is stored separately in:

```text
PushShoppingList/users.json
```

That file contains local account records, Firebase-linked account metadata, generated ntfy topics, notification preferences, account verification/delete tokens, and two-factor settings. Keep it out of commits unless you intentionally want to version local account data.

Common files:

- `recipe_urls.json`: saved recipe URLs and recipe quantities
- `recipe_ingredients.json`: extracted ingredients and scaled quantity data
- `shopping_item_state.json`: checked items, selected stores, and manual item quantities
- `store_settings.json`: store list and enabled stores
- `extract_progress.json`: current extraction progress for the overlay
- `product_choices.json`: saved product candidates, per-store picks, overall picked products, direct product links, embedded image placeholders, and ChatGPT prompt file references
- `product_results.json`: dedicated hybrid shopping results with agent-stage architecture, best products, alternatives, rejected products, rejection reasons, and scoring metadata
- `product_progress.json`: current Grab Best Products progress overlay state
- `raw/product_pages/*.html`: fully rendered Selenium grocery search pages saved for product-ranking review
- `raw/product_pages/*_TEXT.txt`: readable visible text captured from the loaded grocery page
- `raw/product_pages/*_PROMPT_PREVIEW.html`: cleaned rendered HTML excerpt used in the ChatGPT ranking prompt
- `raw/product_pages/*_PRODUCTS.html`: generic visible product-related HTML extracted after scrolling
- `raw/product_prompts/*.json`: full ChatGPT prompt payloads loaded on demand by the Prompt buttons
- `pdf/*.pdf`: archived recipe PDFs created during extraction, including webpage PDFs, upload PDFs, and video caption/transcript PDFs
- `output/*.json`: extracted recipe JSON output. Recipe PDF Cloudflare R2 metadata is saved in each recipe output under `pdf.r2_object_key`, `pdf.r2_public_url`, `pdf.uploaded_at`, and `pdf.cloud_status`.
- `output/sorted_ingredients.txt`: sorted shopping-list text

## Troubleshooting

If recipe extraction says `Missing OPENAI_API_KEY`, set `OPENAI_API_KEY` and restart the app.

If a website returns `403 Forbidden`, the app tries Chrome/Selenium fallback unless `DISABLE_BROWSER_RECIPE_FETCH=1` is set.

If browser fallback hangs or fails, make sure Chrome is installed and updated. Some recipe sites still block automated browsers.

If phone and computer do not show the same progress, use the mesh IP URL on both devices and confirm both are hitting the same Flask server.

If product lookup returns candidates but does not select a strict-rule winner, check the saved food rules and the product's `skip_reasons` in the Alternatives modal. Required food rules remain strict, but each store can still show a best available direct product as `Store Pick`.
