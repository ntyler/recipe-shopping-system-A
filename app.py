import os

from PushShoppingList.app import create_app

app = create_app()


def ssl_context_from_env():
    cert_file = os.getenv("SHOPPING_APP_SSL_CERT", "").strip()
    key_file = os.getenv("SHOPPING_APP_SSL_KEY", "").strip()

    if cert_file and key_file:
        return cert_file, key_file

    if os.getenv("SHOPPING_APP_SSL_ADHOC") == "1":
        return "adhoc"

    return None

if __name__ == "__main__":
    app.run(
        host=os.getenv("SHOPPING_APP_HOST", "0.0.0.0"),
        port=int(os.getenv("SHOPPING_APP_PORT", "5000")),
        debug=False,
        use_reloader=False,
        threaded=True,
        ssl_context=ssl_context_from_env(),
    )
