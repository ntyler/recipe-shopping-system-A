# Recipe Shopping System

Self-hosted recipe-to-shopping-list automation platform with recipe extraction, ingredient parsing, shopping list management, store selection, product lookup, ChatGPT-assisted best-product selection, food-rule review markers, Firebase-backed user accounts, Cloudflare R2 recipe PDF sharing, per-user ntfy notifications, and a mobile-friendly Flask UI.

## Requirements

Use the same Windows Python/OpenAI environment as the backend OpenAI Vision debug path:

```bat
C:\Python39\python.exe app.py
```

You also need:

- Google Chrome installed, for Selenium and browser fallback recipe fetching
- A working internet connection for recipe downloads, OpenAI API calls, Firebase Authentication, Cloudflare R2 uploads, product lookups, and ntfy notifications
- Optional but recommended: Tailscale, ZeroTier, WireGuard, or another mesh/VPN tool if you want to use the app from your phone
- Optional: Cloudflare Tunnel, Tailscale Funnel, ngrok, or another HTTPS tunnel if you want a public HTTPS URL

## Python 3.11 Libraries

Install the Python dependencies from `requirements.txt`:

```powershell
C:\Python39\python.exe -m pip install -r requirements.txt
```

Core libraries used by the project:

- `Flask`: web app and routes
- `waitress`: production WSGI server used when running `app.py` on Windows
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

Optional OpenAI API usage and billing dashboard settings:

```powershell
$env:SHOPPING_APP_OPENAI_PLAN_LABEL="Personal Workspace"
$env:SHOPPING_APP_OPENAI_BILLING_TYPE_LABEL="OpenAI API Pay-As-You-Go"
$env:SHOPPING_APP_OPENAI_MONTHLY_TOKEN_LIMIT="1000000"
$env:SHOPPING_APP_OPENAI_MONTHLY_BUDGET_USD="25"
$env:SHOPPING_APP_OPENAI_INPUT_COST_PER_1M_TOKENS="0.15"
$env:SHOPPING_APP_OPENAI_OUTPUT_COST_PER_1M_TOKENS="0.60"
$env:SHOPPING_APP_OPENAI_BILLING_MARKUP_PERCENT="0"
$env:SHOPPING_APP_OPENAI_MODEL_RATES_JSON='{"gpt-4.1-mini":{"inputCostPer1MTokens":0.15,"outputCostPer1MTokens":0.60,"billableMarkupPercent":0}}'
$env:SHOPPING_APP_OPENAI_FEATURE_COSTS_JSON='{"recipe-step-image":{"fixedCostUsd":0.04}}'
$env:SHOPPING_APP_OPENAI_USAGE_RECORD_LIMIT="2000"
```

The AI Usage & Billing dashboard records OpenAI API usage returned by this shopping-list app's own API responses. It cannot show ChatGPT app, ChatGPT website, ChatGPT Plus/Pro subscription, or OpenAI API usage from other apps.

For user pass-through billing, the app stores an app-owned billing ledger in each user's `openai_usage.json`. Each new record can include raw estimated API cost, configured billable cost, token rates, fixed feature charges, markup percentage, and pricing source. Use `SHOPPING_APP_OPENAI_MODEL_RATES_JSON` for model-specific token rates, `SHOPPING_APP_OPENAI_FEATURE_COSTS_JSON` for fixed charges such as generated images, and `SHOPPING_APP_OPENAI_BILLING_MARKUP_PERCENT` for a default markup. Keep those settings aligned with your current OpenAI API pricing before charging users.

Set these pricing variables in the same PowerShell session that starts the Flask app, or set them permanently with Windows environment-variable tooling and restart the app. If the dashboard shows `Pricing not configured`, usage is being recorded but the running app has not loaded usable API pricing rates.

Optional free local recipe title image generation with ComfyUI:

```powershell
$env:TITLE_IMAGE_PROVIDER="comfyui"
$env:TITLE_IMAGE_FALLBACK_PROVIDER="none"
$env:OLLAMA_URL="http://localhost:11434"
$env:OLLAMA_PROMPT_MODEL="qwen2.5:7b"
$env:COMFYUI_URL="http://127.0.0.1:8188"
```

In `comfyui` mode, Ollama only improves the image prompt. ComfyUI/Stable Diffusion generates the image locally, and OpenAI image generation is not used unless you explicitly set `TITLE_IMAGE_FALLBACK_PROVIDER=openai`.

To use a specific ComfyUI graph from the ComfyUI UI, export it as API JSON and point the app at it:

```powershell
$env:COMFYUI_URL="http://127.0.0.1:8189"
$env:COMFYUI_WORKFLOW_PATH="D:\GitHub\ComfyUI\workflows\recipe_image_api.json"
```

Use `COMFYUI_EQUIPMENT_WORKFLOW_PATH`, `COMFYUI_STEP_WORKFLOW_PATH`, or `COMFYUI_TITLE_WORKFLOW_PATH` when those image types need different graphs. The app patches the exported graph at request time: positive prompt, negative prompt, seed, optional `COMFYUI_IMAGE_WIDTH` / `COMFYUI_IMAGE_HEIGHT`, optional `COMFYUI_CHECKPOINT`, and the SaveImage filename prefix. If auto-detection picks the wrong nodes, set `COMFYUI_POSITIVE_PROMPT_NODE_ID`, `COMFYUI_NEGATIVE_PROMPT_NODE_ID`, `COMFYUI_SEED_NODE_ID`, `COMFYUI_SIZE_NODE_ID`, or `COMFYUI_SAVE_IMAGE_NODE_ID`.

Tyler's local Windows setup:

- ComfyUI is installed at `D:\GitHub\ComfyUI`.
- Start ComfyUI with `D:\GitHub\ComfyUI\start_comfyui_local.bat`.
- ComfyUI serves the local API at `http://127.0.0.1:8188`.
- The installed checkpoint is `D:\GitHub\ComfyUI\models\checkpoints\v1-5-pruned-emaonly-fp16.safetensors`.
- Ollama should keep models only on the E: drive: `E:\Ollama\models`.
- `C:\Users\Tyler\.ollama\models` should remain a junction to `E:\Ollama\models`, not a second model store.
- Keep the user-level `OLLAMA_MODELS` value set to `E:\Ollama\models`.

Optional ntfy topic for phone/computer extraction notifications:

```powershell
$env:NTFY_TOPIC="your-private-shopping-list-topic"
```

Optional SMTP settings for account verification, password reset, signed-in two-factor disable verification, and account deletion verification emails:

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

Required Firebase Authentication settings for account sign-in:

```powershell
$env:FIREBASE_API_KEY="your_web_api_key"
$env:FIREBASE_AUTH_DOMAIN="your-project.firebaseapp.com"
$env:FIREBASE_PROJECT_ID="your-project-id"
$env:FIREBASE_STORAGE_BUCKET="your-project.firebasestorage.app"
$env:FIREBASE_MESSAGING_SENDER_ID="your_sender_id"
$env:FIREBASE_APP_ID="your_web_app_id"
$env:FIREBASE_MEASUREMENT_ID="your_measurement_id"
```

The app intentionally does not ship a real Firebase project config. Use your own Firebase web app values locally and keep service account credentials untracked. For backend verification, set one of these:

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
$env:MENU_ITEM_INFERENCE_WORKERS="8"
$env:PRODUCT_SEARCH_WORKERS="2"
$env:PRODUCT_DETAIL_LIMIT_PER_STORE="4"
$env:PRODUCT_AI_ANALYSIS_LIMIT_PER_STORE="2"
$env:PRODUCT_FINAL_SELECTION_CANDIDATES="96"
$env:PRODUCT_AI_BROWSER_WAIT_SECONDS="4"
```

Optional background job and progress controls:

```powershell
$env:REDIS_URL="redis://localhost:6379/0"
$env:JOB_RETENTION_HOURS="168"
$env:GUEST_JOB_RETENTION_HOURS="24"
$env:JOB_TIMEOUT_MINUTES="180"
$env:WORKER_QUEUES="ai-pantry-menu,ai-pantry-recipe,ai-pantry-media,ai-pantry-product,ai-pantry-light"
$env:JOB_QUEUE_THREAD_FALLBACK="0"
$env:JOB_QUEUE_MODE=""
$env:SHOPPING_APP_JOBS_DB="D:\path\to\jobs.sqlite3"
$env:OPENAI_GLOBAL_MAX_REQUESTS_PER_MINUTE="120"
$env:OPENAI_GLOBAL_MAX_TOKENS_PER_MINUTE="200000"
$env:OPENAI_MENU_MAX_CONCURRENT_CALLS="8"
$env:OPENAI_VISION_MAX_CONCURRENT_CALLS="2"
$env:MENU_RECIPE_BATCH_PROCESSOR_ENABLED="1"
$env:MENU_RECIPE_FAST_MAX_REQUESTS_PER_MINUTE="60"
$env:MENU_RECIPE_FAST_MAX_TOKENS_PER_MINUTE="120000"
$env:MENU_RECIPE_RATE_LIMIT_HEADROOM="0.75"
```

Long-running AI Pantry workflows create persistent job records in a local SQLite job table and enqueue the work through RQ. `SHOPPING_APP_JOBS_DB` defaults to `PushShoppingList/user_data/jobs.sqlite3` when unset. `REDIS_URL` is used only by the Flask server and worker process; never expose it to browser code. `JOB_RETENTION_HOURS` controls signed-in user job history, and `GUEST_JOB_RETENTION_HOURS` controls guest demo job history. Guest job records are removed during demo cleanup. Set `JOB_QUEUE_THREAD_FALLBACK=0` for production-style runs so Redis/RQ outages fail safely instead of running jobs inside Flask. If Redis or RQ is unavailable in local development, `JOB_QUEUE_THREAD_FALLBACK=1` lets Flask run jobs in a background thread so the progress UI can still be tested. Set `JOB_QUEUE_MODE=inline` only for targeted debugging or tests where the request should run the job synchronously.

Notes:

- Leave `DISABLE_BROWSER_RECIPE_FETCH` unset unless you do not want Selenium/Chrome fallback.
- Leave `DISABLE_RECIPE_HTML_CACHE_FALLBACK` unset if you want the app to reuse cached recipe HTML when a live page fails.
- Leave `DISABLE_RECIPE_PDF_ARCHIVE` unset if you want each extracted recipe page saved as a PDF for later review.
- Set `FORCE_OPENAI_RECIPE_EXTRACTION=1` only when you want the OpenAI extractor used even if recipe-card HTML already has enough structured data.
- `MENU_ITEM_INFERENCE_WORKERS` controls how many restaurant menu item recipe predictions run at once during Menu Extract imports. The default is `8`, and the app clamps it between `1` and `32`.
- `MENU_RECIPE_BATCH_PROCESSOR_ENABLED=1` keeps Generate Menu Recipes on the app's local parallel batch dispatcher. Set `MENU_RECIPE_FAST_MAX_REQUESTS_PER_MINUTE` / `MENU_RECIPE_FULL_MAX_REQUESTS_PER_MINUTE` and `MENU_RECIPE_FAST_MAX_TOKENS_PER_MINUTE` / `MENU_RECIPE_FULL_MAX_TOKENS_PER_MINUTE` to throttle how quickly a single menu generation job starts OpenAI batches. If those are unset, the dispatcher falls back to the global OpenAI RPM/TPM env vars; `MENU_RECIPE_RATE_LIMIT_HEADROOM` can reserve extra room below the configured limit.
- Leave `SHOPPING_APP_PORT` unset when running `C:\Python39\python.exe app.py` directly and you want the default port `5000`. The included `start_app.bat` currently sets `SHOPPING_APP_PORT=5083`.
- `C:\Python39\python.exe app.py` serves through Waitress by default. Set `SHOPPING_APP_SERVER=flask-dev` only if you intentionally need Flask's development server for local debugging.
- Set `SHOPPING_APP_PASSWORD_RESET_BASE_URL` to the address users should open from password reset emails and signed-in two-factor disable verification emails, such as your LAN, Tailscale, or public HTTPS URL. If unset, reset emails use the current request host.
- Set `SHOPPING_APP_ACCOUNT_LINK_BASE_URL` to the address users should open from account verification and account deletion emails. If unset, account links fall back to `SHOPPING_APP_PASSWORD_RESET_BASE_URL` or the current request host.
- Product lookup uses `OPENAI_API_KEY` for fully loaded product-page analysis and final best-product selection. If no key is set, the app still parses product candidates but skips ChatGPT product analysis.
- Social/video recipe imports, including YouTube Shorts, use public title, caption, description, transcript text, and local parsing first. If text-only extraction cannot find ingredients and `OPENAI_API_KEY` is set, the app can fall back to audio transcription plus video thumbnail images to ask OpenAI for a recipe. YouTube audio downloads default to yt-dlp's Android player client because the standard web client can return HTTP 403 for Shorts; override with `YTDLP_YOUTUBE_PLAYER_CLIENTS` such as `android,web`, or set it to `off` if you want the raw yt-dlp default. The fallback is tracked as `social-video-audio-image-extraction` in AI Usage & Billing.
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
C:\Python39\python.exe app.py
```

Then open:

```text
http://127.0.0.1:5000
```

That direct command uses Waitress and the default port `5000` unless `SHOPPING_APP_PORT` is set.

Or use:

```powershell
.\start_app.bat
```

The included launcher currently sets `SHOPPING_APP_PORT=5083`, so it opens:

```text
http://127.0.0.1:5083
```

For production-style background processing, start Redis and run one or more RQ workers alongside the Flask app:

Local Redis with Docker Desktop on Windows:

```powershell
docker run --name ai-pantry-redis -p 6379:6379 -d redis:7
$env:REDIS_URL="redis://localhost:6379/0"
```

If the container already exists:

```powershell
docker start ai-pantry-redis
```

```powershell
$env:REDIS_URL="redis://localhost:6379/0"
$env:JOB_QUEUE_THREAD_FALLBACK="0"
python app.py
```

Menu worker:

```powershell
$env:REDIS_URL="redis://localhost:6379/0"
$env:WORKER_QUEUES="ai-pantry-menu"
python worker.py
```

General worker:

```powershell
$env:REDIS_URL="redis://localhost:6379/0"
$env:WORKER_QUEUES="ai-pantry-recipe,ai-pantry-media,ai-pantry-light"
python worker.py
```

Product workers can listen on `ai-pantry-product`, or a single worker can listen to multiple queues with `WORKER_QUEUES="ai-pantry-menu,ai-pantry-recipe,ai-pantry-media,ai-pantry-product,ai-pantry-light"`.

On Windows local development, Redis can run through Docker Desktop, WSL, Memurai, or another Redis-compatible service. In production, run Redis as a private service reachable by the Flask app and worker, set the same `REDIS_URL` in both processes, and keep service credentials out of frontend templates and JavaScript.

Queue readiness is logged at app startup with `[Job Queue] action=startup_diagnostics`. For Redis/RQ mode, confirm the line includes `redis_package_installed=true`, `rq_package_installed=true`, `redis_url_configured=true`, `redis_connection_succeeded=true`, and `mode=redis/rq`. Menu imports should then log `[Job Queue] action=rq_enqueued ... queue=ai-pantry-menu`, and the worker should log `[Job Worker] action=start ... execution=rq`. If Redis is missing or unavailable, the startup log shows a distinct `reason` such as `missing_redis_package`, `missing_rq_package`, `invalid_redis_url`, or `redis_connection_failed`; fallback jobs log `[Job Queue] action=thread_fallback_started ... reason=<reason>`.

After signing in, the queue diagnostic endpoint returns the same readiness details:

```text
http://127.0.0.1:5000/api/debug/job-queue
```

The app also listens on your LAN address, so another device on the same Wi-Fi can open:

```text
http://<computer-lan-ip>:5000
```

If you use `start_app.bat`, replace `5000` with `5083`.

Example LAN URL:

```text
http://<computer-lan-ip>:5083
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
- `admin@example.com` and `ntylerbert@gmail.com` are treated as `Admin`; other signed-in users are `User` unless code or stored user data changes.
- The signed-in account card stays focused on profile photo, name, email, role, email verification status, created date, and last sign-in date.

Account Menu groups and items:

- `Profile`
  - `Account Settings`: edit first name, last name, username, email, and uploaded logo/avatar.
  - `Account Notices`: opens recent and historical admin-support account access notices when the account has them.
- `Usage & Billing`
  - `AI Usage & Billing`: opens OpenAI API usage and billing totals for this app, including plan, billing type, monthly API budget, API requests, input/output/total tokens, raw estimated API cost, billable AI cost, activity counters, budget status, lifetime tokens, and last API request. The dashboard records usage from this app's OpenAI API responses in per-user `openai_usage.json`; it does not expose ChatGPT app, ChatGPT website, ChatGPT Plus/Pro subscription, or OpenAI API usage from other apps. App activity counters such as `Recipe Imports` count successful app actions even when the recipe was imported from structured recipe data without an OpenAI API request.
- `Security`
  - `Change Password`: sends the Firebase password reset/change flow for Firebase users.
  - `Verify Email` or `Email Verified`: verified accounts show a disabled `Email Verified` item instead of an action button.
  - `Two-Factor Authentication`: opens the authenticator app and backup-code panel.
- `Communications`
  - `Push Notifications`: opens notification status, devices, and preferences.
  - `Feedback & Support`: opens the Feedback & Support section with request count and `support@recipeshoppinglist.com`.
- `Session`
  - `Sign Out`: signs out of Firebase and clears the Flask session.
- `Danger Zone`
  - `Delete Account`: sends a one-time email verification link before deleting the account.

The account panel that is open in this browser is remembered across page refreshes for `Account Settings`, `Account Notices`, `AI Usage & Billing`, `Two-Factor Authentication`, `Push Notifications`, and `Delete Account`. Closing the panel clears that remembered state.

The Account Menu should stay compact, left-aligned, and grouped. Menu rows use a fixed icon column so labels line up consistently.

Profile photos use the uploaded logo/avatar first. If the uploaded logo is removed, the account falls back to the Firebase/Google profile photo when available, then to the generated initial avatar.

### Private Data And Admin Support

Private data is anything that can identify a user, reveal something personal about them, or let someone access or control their account.

Treat these as private in this app:

- Account identity: email, phone number, full name, username, and Firebase UID.
- Location/contact data: home address, delivery address, and store pickup address.
- Security secrets: passwords, password hashes, two-factor secrets, backup codes, trusted-device tokens, session cookies, and reset tokens.
- Store credentials: grocery login usernames/passwords and saved store account data.
- User content: imported recipes, uploaded docs/photos/PDFs, pantry contents, shopping list items, and receipt data.
- Security metadata: last sign-in, two-factor status, notification topics, device info, IP logs, and user-agent logs.
- Admin/support audit data: who viewed an account, when, and why.

For admin support, use the safer rule: admins can see support-safe summaries, not raw private data.

Support-safe examples:

- Account status
- Email verified yes/no
- Two-factor enabled yes/no
- Backup codes remaining count
- Last sign-in date
- Workspace file counts

Do not show admins:

- Actual passwords or password hashes
- Two-factor secrets or backup code values
- Home address
- Store passwords
- Private recipe, shopping, pantry, receipt, upload, or PDF contents unless the user explicitly asks for help with that specific data.

The `Account Notices` menu item opens the latest two admin-support access events. Users can click `View account access history` inside that panel to show the full sanitized admin-support access history for their account.

User-facing support and audit displays must show the public support identity, not a staff member's personal Gmail address. Store admin-support audit rows with both `actorPrivateEmail` for internal tracing and `actorPublicEmail` for user-facing notices/emails. End users should only see `support@recipeshoppinglist.com`; internal admin pages may continue showing `actorPrivateEmail`. Normalize old support log entries that only have `actorEmail`, `admin_email`, or `actorPrivateEmail` before rendering them to users.

Two-factor authentication is account-specific:

- Setup uses an authenticator app secret, QR code when available, and one-time backup codes.
- First-time setup asks the user to confirm the new authenticator code once with a setup-specific confirmation screen.
- Sign-in can remember the browser for 30 days.
- Backup-code regeneration requires an authenticator code or backup code.
- Normal disable requires an authenticator code or backup code.
- The public two-factor sign-in challenge does not offer an email-disable option. It requires the authenticator app code or a backup code.
- If a signed-in user is already inside their account and needs to retire a lost authenticator, the account menu can send a one-time disable verification link to that account email.
- Email disable links are tied to the account that requested the email. Opening the link should not switch to another signed-in account.
- Admin lockout recovery is local-only. Run the break-glass script from the app host, not through a web route:

```powershell
py -3.11 PushShoppingList\scripts\disable_2fa.py --email ntylerbert@gmail.com --confirm
```

To intentionally unlock a non-admin user from the local host:

```powershell
py -3.11 PushShoppingList\scripts\disable_2fa.py --email user@example.com --allow-non-admin --confirm
```

- Account action pages for password reset, signed-in two-factor disable verification, and account deletion should remain visible until the user completes the action or clicks cancel.

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

The Waitress app server listens on all network interfaces:

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

Example tailnet URL:

```text
https://your-windows-host.your-tailnet.ts.net/
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

Example public Funnel URL:

```text
https://your-windows-host.your-tailnet.ts.net/
```

Turn off public Funnel access:

```powershell
tailscale funnel --https=443 off
```

Important: Funnel exposes the app on the public internet. Do not leave Funnel running unless you are comfortable with anyone who has the URL reaching the app.

### Private Mesh/VPN Access

For phone access without making the app public, put your computer and phone on the same private mesh network.

Recommended setup:

1. Install Tailscale, ZeroTier, or WireGuard on the computer running the app.
2. Install the same mesh/VPN app on your phone.
3. Join both devices to the same private network.
4. Start the app on the computer.
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
https://your-windows-host.your-tailnet.ts.net/
```

Waitress serves HTTP only. For the most reliable phone experience, use Tailscale Funnel, Cloudflare Tunnel, ngrok, Nginx, or another HTTPS proxy in front of the app.

Temporary local self-signed certificates are still available through Flask's development server when you intentionally opt into it:

```powershell
$env:SHOPPING_APP_SERVER="flask-dev"
$env:SHOPPING_APP_SSL_ADHOC="1"
$env:SHOPPING_APP_PORT="5083"
C:\Python39\python.exe app.py
```

Then open:

```text
https://<computer-ip>:5083
```

Your browser will warn because the certificate is self-signed. For the most reliable phone experience, use one of these:

- A trusted local certificate through Flask's development server, then start with:

```powershell
$env:SHOPPING_APP_SERVER="flask-dev"
$env:SHOPPING_APP_SSL_CERT="C:\path\to\cert.pem"
$env:SHOPPING_APP_SSL_KEY="C:\path\to\key.pem"
C:\Python39\python.exe app.py
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

Signed-in users get their own generated topic stored with their account. Open `Account Menu > Communications > Push Notifications` to enable/disable notifications, open the topic, copy the topic link, send a test notification, and manage preferences.

Notification preferences currently include:

- Recipe Import Complete
- Recipe PDF Generated
- Cloudflare Upload Complete
- Store Search Complete
- Shopping List Updated
- Pantry Expiration Reminders
- Feedback Response
- Security Alerts

Device display is ready for multi-device notification management and currently shows devices such as Windows PC, iPhone, and Browser when available.

AI Pantry expiration reminders are sent by a small daily scanner. It checks signed-in users' pantry inventory for due expiration or freeze-by dates, sends one reminder per item/date, and records the reminder marker to avoid duplicate alerts. Run a dry check with:

```powershell
python PushShoppingList\scripts\send_pantry_reminders.py --dry-run
```

For scheduled reminders on Windows, run that script without `--dry-run` from Task Scheduler once per day while the same app environment variables are available.

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
4. Start the app.
5. Open the app signed out.
6. Confirm no Firebase setup/debug banners appear.
7. Create an account with email/password.
8. Confirm the backend Flask session is created.
9. Sign out.
10. Sign in with email/password.
11. Test forgot password.
12. Test Google sign-in.
13. Sign in as `admin@example.com` or `ntylerbert@gmail.com` and confirm the Admin role and Admin access enabled badge.
14. Sign in as another user and confirm the User role.
15. Confirm `Connected via Firebase Authentication` appears only after backend session verification succeeds.
16. Confirm email verification status is shown. If the email is already verified, the Account Menu item should read `Email Verified` and be disabled.
17. Confirm Account Menu contains Profile, Usage & Billing, Security, Communications, Session, and Danger Zone groups. Confirm rows are left-aligned with a consistent icon column.
18. Confirm Account Menu contains Account Settings, Account Notices when notices exist, AI Usage & Billing, Change Password, Verify Email or Email Verified, Two-Factor Authentication, Push Notifications, Feedback & Support, Sign Out, and Delete Account.
19. Confirm Account Settings can remove an uploaded logo/avatar and falls back to the Firebase/Google profile photo when available.
20. Confirm Account Settings, Account Notices, AI Usage & Billing, Two-Factor Authentication, Push Notifications, and Delete Account stay open after a page refresh and clear that remembered state after Close.
21. Confirm normal two-factor disable requires an authenticator code or backup code.
22. Confirm the public two-factor sign-in challenge does not show an email-disable recovery option.
23. Confirm a pending two-factor sign-in session cannot request a disable verification email.
24. Confirm two-factor authentication is account-specific. A disable verification link emailed from a signed-in account should disable only that account's two-factor settings.
25. Confirm local admin recovery works only from the app host with `PushShoppingList\scripts\disable_2fa.py`, and that non-admin accounts require `--allow-non-admin`.
26. Confirm account action pages for password reset, signed-in two-factor disable verification, and account deletion do not collapse into a blank screen before the user completes or cancels the action.
27. Confirm Push Notifications lives inside Account Menu and can enable, disable, send a test notification, and update preferences.
28. Confirm signed-out users cannot manage protected sections.
29. Confirm a signed-in admin user can create and upload a PDF to Cloudflare R2.
30. Confirm Copy PDF Link copies an R2 URL.
31. Confirm the copied PDF link does not contain localhost, 127.0.0.1, trycloudflare, or the app tunnel hostname.
32. Confirm `/recipe_archive_pdf?url=<recipe_url>` redirects to the R2 public URL after the first generated upload.
33. Confirm secrets, service account JSON files, and generated PDFs are not shown in `git status`.

## Important Data Files

Most app state is stored under:

```text
PushShoppingList/services/recipe-extractor/data/
```

Account state is stored separately in:

```text
PushShoppingList/users.json
```

That file contains local account records, Firebase-linked account metadata, generated ntfy topics, notification preferences, account verification/delete tokens, two-factor settings, and local admin two-factor unlock metadata. Keep it out of commits unless you intentionally want to version local account data.

Common files:

- `recipe_urls.json`: saved recipe URLs and recipe quantities
- `recipe_ingredients.json`: extracted ingredients and scaled quantity data
- `shopping_item_state.json`: checked items, selected stores, and manual item quantities
- `store_settings.json`: store list and enabled stores
- `extract_progress.json`: current extraction progress for the overlay
- `product_choices.json`: saved product candidates, per-store picks, overall picked products, direct product links, embedded image placeholders, and ChatGPT prompt file references
- `openai_usage.json`: per-user OpenAI API token usage and app-owned billing ledger records, including raw estimated cost, billable cost, configured rates, markup, fixed feature charges, and pricing source for AI Usage & Billing
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
