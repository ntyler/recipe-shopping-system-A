@echo off

cd /d D:\GitHub\recipe-shopping-system-A

echo Starting Flask app...

set SHOPPING_APP_PORT=5055
set PRODUCT_SEARCH_WORKERS=2
set PRODUCT_DETAIL_LIMIT_PER_STORE=3
set PRODUCT_AI_ANALYSIS_LIMIT_PER_STORE=1
set PRODUCT_AI_BROWSER_WAIT_SECONDS=4
start http://127.0.0.1:5055

py -3.11 app.py
