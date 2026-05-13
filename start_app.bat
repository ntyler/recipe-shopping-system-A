@echo off

cd /d D:\GitHub\recipe-shopping-system-A

echo Starting Flask app...

py -3.11 app.py

start http://127.0.0.1:5000
