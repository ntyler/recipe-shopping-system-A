@echo off

cd /d D:\GitHub\recipe-shopping-system-A

echo Starting Flask app over HTTPS with a temporary self-signed certificate...
echo.
echo Local computer:
echo   https://127.0.0.1:5000
echo.
echo Phone on LAN:
echo   https://YOUR-COMPUTER-IP:5000
echo.
echo Your browser will show a certificate warning because this is self-signed.
echo For reliable phone geolocation, use a trusted certificate or an HTTPS tunnel.
echo.

set SHOPPING_APP_SSL_ADHOC=1
start https://127.0.0.1:5000

py -3.11 app.py
