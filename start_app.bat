@echo off

cd /d D:\GitHub\recipe-shopping-system-A

echo Starting Flask app...

set SHOPPING_APP_PORT=5001
start http://127.0.0.1:5001

py -3.11 app.py
