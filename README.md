# Recipe Shopping System

Self-hosted recipe-to-shopping-list automation platform with recipe extraction, ingredient parsing, shopping list management, store selection, product lookup, ChatGPT-assisted best-product selection, food-rule review markers, and a mobile-friendly Flask UI.

## Requirements

Use **Python 3.11** for this project. The included `start_app.bat` runs the app with:

```bat
py -3.11 app.py
```

You also need:

- Google Chrome installed, for Selenium and browser fallback recipe fetching
- A working internet connection for recipe downloads, OpenAI API calls, product lookups, and ntfy notifications
- Optional but recommended: Tailscale, ZeroTier, WireGuard, or another mesh/VPN tool if you want to use the app from your phone
- Optional: Tailscale Funnel if you want a temporary public HTTPS URL

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

Optional recipe-fetch controls:

```powershell
$env:DISABLE_BROWSER_RECIPE_FETCH="1"
$env:DISABLE_RECIPE_HTML_CACHE_FALLBACK="1"
$env:DISABLE_RECIPE_PDF_ARCHIVE="1"
$env:FORCE_OPENAI_RECIPE_EXTRACTION="1"
```

Optional app and product-lookup controls:

```powershell
$env:SHOPPING_APP_PORT="5061"
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
- Leave `SHOPPING_APP_PORT` unset when running `py -3.11 app.py` directly and you want the default Flask port `5000`. The included `start_app.bat` currently sets `SHOPPING_APP_PORT=5061`.
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

The included launcher currently sets `SHOPPING_APP_PORT=5061`, so it opens:

```text
http://127.0.0.1:5061
```

The app also listens on your LAN address, so another device on the same Wi-Fi can open:

```text
http://<computer-lan-ip>:5000
```

If you use `start_app.bat`, replace `5000` with `5061`.

Example from the current setup:

```text
http://192.168.68.62:5061
```

## Best Product Lookup

The **Grab Best Products** button searches the activated stores near the saved Full Address for every shopping-list item. The current workflow is:

1. The Planner Agent builds item/store searches from the shopping list and saved Full Address.
2. The Store Resolution Agent resolves the nearest pickup-oriented location for each activated store.
3. Browser Worker Agents run in parallel with `ThreadPoolExecutor`, open the real grocery search/category pages with Selenium/undetected Chrome, apply the saved address context, select the nearest pickup-oriented store when the page exposes a store selector, and scroll until no new product cards appear.
4. The Product Extraction/Normalization Agent saves the fully rendered page HTML under `data/raw/product_pages/`, plus readable `_TEXT.txt` and cleaned `_PROMPT_PREVIEW.html` snapshots for debugging. It captures every visible product card up to `PRODUCT_CANDIDATE_LIMIT_PER_STORE` and normalizes store name, store address, product name, brand, size/count, price, unit price, stock status, direct product URL, image URL, cleaned raw product-card HTML snippet, and embedded image Base64 where possible.
5. Shortlisted candidates are opened on their full product detail pages for deeper evidence.
6. The Validation Layer rejects irrelevant, unavailable, search-page-only, or rule-failing products while saving rejection reasons.
7. The Ranking Agent sends the saved rules, a cleaned excerpt of the fully rendered Selenium HTML, and the extracted product-card HTML/data to ChatGPT when `OPENAI_API_KEY` is available. ChatGPT does not browse store websites; it ranks the supplied page/card data into best product, valid alternatives, and rejected products with rejection reasons and confidence scores.
8. Results are saved with the best product, valid alternatives, rejected products, rejection reasons, scoring metadata, manual selection metadata, and store/ingredient metadata.

For eggs, the built-in ranking prefers standard shell egg cartons, 12-count or larger cartons, availability, nearby stores, and lower price per egg. It avoids unrelated egg products such as liquid eggs, egg whites only, boiled eggs, egg bites, and plant-based egg substitutes when possible.

The UI shows:

- `Picked`: the overall strict-rule product selected across stores.
- `Store Pick`: the best direct product found for that store. If the product does not satisfy strict rules, it can still be shown as the store's best available candidate while preserving the rule issue in the saved choice.
- Each enabled store under each ingredient, with the store's best product price beside it.
- Product names as direct links to product pages, not search pages, whenever a direct product URL is available.
- An `Alternatives` button beside each store that shows valid alternatives and rejected products with reasons.
- A `Prompt` button on store picks and picked products so you can inspect the extracted-card prompt sent to the ChatGPT API. Full prompts are stored under `raw/product_prompts/` and loaded only when requested.
- Manual alternative selections persist as `selected_by_user` with `selected_at`.

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
tailscale serve --bg http://127.0.0.1:5061
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
tailscale funnel --bg --yes http://127.0.0.1:5061
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

If you use the included launcher, use port `5061` instead:

```text
http://<computer-mesh-ip>:5061
```

Examples:

```text
http://100.x.y.z:5061
http://10.x.y.z:5061
```

## HTTPS / Secure Page Access

Phone GPS/geolocation requires a secure browser origin. `http://<ip>:5000` or `http://<ip>:5061` will show as **Not Secure**, so mobile browsers may block `Use My Location`.

Tailscale Serve and Tailscale Funnel provide HTTPS at:

```text
https://desktop-in7s09s.tail906b20.ts.net/
```

Quick test with Flask's temporary self-signed certificate:

```powershell
$env:SHOPPING_APP_SSL_ADHOC="1"
$env:SHOPPING_APP_PORT="5061"
py -3.11 app.py
```

Then open:

```text
https://<computer-ip>:5061
```

Your browser will warn because the certificate is self-signed. For the most reliable phone experience, use one of these:

- A trusted local certificate, then start with:

```powershell
$env:SHOPPING_APP_SSL_CERT="C:\path\to\cert.pem"
$env:SHOPPING_APP_SSL_KEY="C:\path\to\key.pem"
py -3.11 app.py
```

- A trusted HTTPS tunnel such as Tailscale Funnel, Cloudflare Tunnel, or ngrok pointed at `http://127.0.0.1:5000`.
- For the included `start_app.bat`, point the tunnel at `http://127.0.0.1:5061`.

Do not expose this app publicly unless you add authentication, keep the tunnel private, or only run public access temporarily.

If the phone cannot connect:

- Confirm both devices are online in the mesh/VPN app.
- Allow Python/Flask through Windows Firewall for private networks.
- Make sure nothing else is already using the port you started Flask on, usually `5000` for direct runs or `5061` for `start_app.bat`.
- Use the mesh IP, not `127.0.0.1`; `127.0.0.1` only works on the same device.

## ntfy Notifications

The app can send extraction started/complete/cancelled notifications through `ntfy.sh`.

1. Pick a private topic name.
2. Set `NTFY_TOPIC` to that topic.
3. Subscribe to the same topic on your phone using the ntfy app or website.

Example:

```powershell
$env:NTFY_TOPIC="nathaniel-shopping-list-12345"
```

Notifications are best treated as convenience alerts. The actual UI sync comes from the Flask page polling the extraction progress file.

## Important Data Files

Most app state is stored under:

```text
PushShoppingList/services/recipe-extractor/data/
```

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
- `raw/product_prompts/*.json`: full ChatGPT prompt payloads loaded on demand by the Prompt buttons
- `pdf/*.pdf`: archived recipe PDFs created during extraction, including webpage PDFs, upload PDFs, and video caption/transcript PDFs
- `output/*.json`: extracted recipe JSON output
- `output/sorted_ingredients.txt`: sorted shopping-list text

## Troubleshooting

If recipe extraction says `Missing OPENAI_API_KEY`, set `OPENAI_API_KEY` and restart the app.

If a website returns `403 Forbidden`, the app tries Chrome/Selenium fallback unless `DISABLE_BROWSER_RECIPE_FETCH=1` is set.

If browser fallback hangs or fails, make sure Chrome is installed and updated. Some recipe sites still block automated browsers.

If phone and computer do not show the same progress, use the mesh IP URL on both devices and confirm both are hitting the same Flask server.

If product lookup returns candidates but does not select a strict-rule winner, check the saved food rules and the product's `skip_reasons` in the Alternatives modal. Required food rules remain strict, but each store can still show a best available direct product as `Store Pick`.
