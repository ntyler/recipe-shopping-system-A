@echo off

cd /d D:\GitHub\recipe-shopping-system-A

echo Starting Flask app...

set SHOPPING_APP_PORT=5083
call :load_user_env SHOPPING_APP_SMTP_HOST
call :load_user_env SHOPPING_APP_SMTP_PORT
call :load_user_env SHOPPING_APP_SMTP_USERNAME
call :load_user_env SHOPPING_APP_SMTP_PASSWORD
call :load_user_env SHOPPING_APP_SMTP_FROM_EMAIL
call :load_user_env SHOPPING_APP_SMTP_FROM_NAME
call :load_user_env SHOPPING_APP_SMTP_USE_TLS
call :load_user_env SHOPPING_APP_PASSWORD_RESET_BASE_URL
if exist local_env.bat call local_env.bat
set PRODUCT_SEARCH_WORKERS=2
set PRODUCT_DETAIL_LIMIT_PER_STORE=4
set PRODUCT_AI_ANALYSIS_LIMIT_PER_STORE=2
set PRODUCT_FINAL_SELECTION_CANDIDATES=96
set PRODUCT_AI_BROWSER_WAIT_SECONDS=4
start http://127.0.0.1:%SHOPPING_APP_PORT%

py -3.11 app.py
goto :eof

:load_user_env
for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v %~1 2^>nul') do set "%~1=%%B"
goto :eof
