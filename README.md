# Recipe Shopping System

Self-hosted recipe-to-shopping-list automation platform with recipe extraction, ingredient parsing, shopping list management, store selection, product lookup, food-rule review markers, and a mobile-friendly Flask UI.

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
$env:FORCE_OPENAI_RECIPE_EXTRACTION="1"
```

Notes:

- Leave `DISABLE_BROWSER_RECIPE_FETCH` unset unless you do not want Selenium/Chrome fallback.
- Leave `DISABLE_RECIPE_HTML_CACHE_FALLBACK` unset if you want the app to reuse cached recipe HTML when a live page fails.
- Set `FORCE_OPENAI_RECIPE_EXTRACTION=1` only when you want the OpenAI extractor used even if recipe-card HTML already has enough structured data.

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

Or use:

```powershell
.\start_app.bat
```

The app also listens on your LAN address, so another device on the same Wi-Fi can open:

```text
http://<computer-lan-ip>:5000
```

Example from the current setup:

```text
http://192.168.68.62:5000
```

## Tailscale Access

The Flask app listens on all network interfaces:

```python
host="0.0.0.0"
port=5000
```

### Tailnet-Only Access

Use Tailscale Serve when you only want devices in your Tailscale tailnet to reach the app:

```powershell
tailscale serve --bg http://127.0.0.1:5000
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
tailscale funnel --bg --yes http://127.0.0.1:5000
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

Examples:

```text
http://100.x.y.z:5000
http://10.x.y.z:5000
```

## HTTPS / Secure Page Access

Phone GPS/geolocation requires a secure browser origin. `http://<ip>:5000` will show as **Not Secure**, so mobile browsers may block `Use My Location`.

Tailscale Serve and Tailscale Funnel provide HTTPS at:

```text
https://desktop-in7s09s.tail906b20.ts.net/
```

Quick test with Flask's temporary self-signed certificate:

```powershell
.\start_app_https_adhoc.bat
```

Then open:

```text
https://<computer-ip>:5000
```

Your browser will warn because the certificate is self-signed. For the most reliable phone experience, use one of these:

- A trusted local certificate, then start with:

```powershell
$env:SHOPPING_APP_SSL_CERT="C:\path\to\cert.pem"
$env:SHOPPING_APP_SSL_KEY="C:\path\to\key.pem"
py -3.11 app.py
```

- A trusted HTTPS tunnel such as Tailscale Funnel, Cloudflare Tunnel, or ngrok pointed at `http://127.0.0.1:5000`.

Do not expose this app publicly unless you add authentication, keep the tunnel private, or only run public access temporarily.

If the phone cannot connect:

- Confirm both devices are online in the mesh/VPN app.
- Allow Python/Flask through Windows Firewall for private networks.
- Make sure nothing else is already using port `5000`.
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
- `output/*.json`: extracted recipe JSON output
- `output/sorted_ingredients.txt`: sorted shopping-list text

## Troubleshooting

If recipe extraction says `Missing OPENAI_API_KEY`, set `OPENAI_API_KEY` and restart the app.

If a website returns `403 Forbidden`, the app tries Chrome/Selenium fallback unless `DISABLE_BROWSER_RECIPE_FETCH=1` is set.

If browser fallback hangs or fails, make sure Chrome is installed and updated. Some recipe sites still block automated browsers.

If phone and computer do not show the same progress, use the mesh IP URL on both devices and confirm both are hitting the same Flask server.
