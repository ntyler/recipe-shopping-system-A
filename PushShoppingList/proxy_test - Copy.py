from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

WEBTOP_URL = "/"

CONTAINER_NAME = "webtop"
DOCKER_USER = "abc"

STORE_URLS = {
    "aldi": "https://www.aldi.us/store/aldi/storefront",
    "meijer": "https://www.meijer.com/shopping/search.html",
    "walmart": "https://www.walmart.com",
    "kroger": "https://www.kroger.com",
    "target": "https://www.target.com",
}

CHROME_FLAGS = (
    'DISPLAY=:1 '
    'HOME=/config '
    'google-chrome '
    '--no-sandbox '
    '--guest '
    '--disable-sync '
    '--disable-signin-promo '
    '--no-first-run '
    '--no-default-browser-check '
    '--disable-background-networking '
    '--disable-component-update '
    '--disable-default-apps '
    '--disable-extensions '
    '--disable-session-crashed-bubble '
    '--disable-features=Translate,AutofillServerCommunication,OptimizationHints '
    '--password-store=basic '
    '--use-mock-keychain '
    '--user-data-dir=/config/google-chrome-profile'
)

HTML = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Docker Embedded Store Browser</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <style>
        body {{
            margin: 0;
            background: #1e1f22;
            color: white;
            font-family: Arial, sans-serif;
        }}

        .topbar {{
            padding: 10px;
            background: #2a2d31;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            border-bottom: 1px solid #444;
        }}

        button {{
            padding: 10px 14px;
            border-radius: 8px;
            border: none;
            background: #2563eb;
            color: white;
            font-weight: bold;
            cursor: pointer;
        }}

        .secondary {{
            background: #4b5563;
        }}

        .danger {{
            background: #dc2626;
        }}

        .status {{
            padding: 8px 12px;
            background: #111827;
            border-bottom: 1px solid #444;
            font-size: 14px;
        }}

        iframe {{
            width: 100%;
            height: calc(100vh - 95px);
            border: none;
            background: black;
        }}
    </style>
</head>

<body>

<div class="topbar">
    <button onclick="openStore('aldi')">Open Aldi</button>
    <button onclick="openStore('meijer')">Open Meijer</button>
    <button onclick="openStore('walmart')">Open Walmart</button>
    <button onclick="openStore('kroger')">Open Kroger</button>
    <button onclick="openStore('target')">Open Target</button>

    <button class="secondary" onclick="reloadFrame()">Reload Docker Browser</button>
    <button class="danger" onclick="closeFrame()">Close</button>
</div>

<div class="status" id="status">
    Docker Webtop ready.
</div>

<iframe id="dockerFrame" src="{WEBTOP_URL}"></iframe>

<script>
const WEBTOP_URL = "{WEBTOP_URL}";

async function openStore(store) {{
    document.getElementById("status").innerText = "Opening " + store + "...";

    const res = await fetch("/app/open_url", {{
        method: "POST",
        headers: {{
            "Content-Type": "application/json"
        }},
        body: JSON.stringify({{ store }})
    }});

    const data = await res.json();
    document.getElementById("status").innerText = data.message;
}}

function reloadFrame() {{
    document.getElementById("dockerFrame").src = WEBTOP_URL;
    document.getElementById("status").innerText = "Docker browser reloaded.";
}}

function closeFrame() {{
    document.getElementById("dockerFrame").src = "about:blank";
    document.getElementById("status").innerText = "Docker browser closed.";
}}
</script>

</body>
</html>
"""


@app.route("/")
def index():
    return HTML


@app.route("/open_url", methods=["POST"])
def open_url():
    data = request.get_json(force=True)
    store = str(data.get("store", "")).lower().strip()

    url = STORE_URLS.get(store)

    if not url:
        return jsonify({
            "ok": False,
            "message": "Unknown store."
        }), 400

    result = open_url_in_docker(url)

    if result["ok"]:
        return jsonify({
            "ok": True,
            "message": f"Opened {store}: {url}"
        })

    return jsonify({
        "ok": False,
        "message": result["error"]
    }), 500


def open_url_in_docker(url):
    command = f'{CHROME_FLAGS} "{url}"'

    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                DOCKER_USER,
                "-d",
                CONTAINER_NAME,
                "bash",
                "-lc",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return {"ok": True}

        return {
            "ok": False,
            "error": result.stderr or result.stdout or "Docker command failed."
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        threaded=True,
        use_reloader=False,
    )
