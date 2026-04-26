@echo off
echo Adding Windows Firewall rule for BroadLink UDP traffic...
netsh advfirewall firewall add rule name="BroadLink AC Controller" dir=in action=allow protocol=UDP remoteip=192.168.1.74
netsh advfirewall firewall add rule name="BroadLink AC Controller Out" dir=out action=allow protocol=UDP remoteip=192.168.1.74
echo.
echo Rule added! Now running discovery...
echo.
python discover.py
pause
