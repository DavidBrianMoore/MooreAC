@echo off
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting AC Freedom Controller...
echo Open http://localhost:5000 in your browser
echo.
python server.py
pause
