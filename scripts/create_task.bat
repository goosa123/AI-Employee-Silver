@echo off
schtasks /create ^
  /tn "AI-Employee-Silver-Watchers" ^
  /tr "\"C:\Users\ASUS\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe\" \"C:\Users\ASUS\Claude Projects\AI-Employee-Silver\watchers\launcher.py\"" ^
  /sc onlogon ^
  /ru "%USERNAME%" ^
  /delay 0000:30 ^
  /f
echo.
echo Task created. Verify:
schtasks /query /tn "AI-Employee-Silver-Watchers" /fo LIST
pause
