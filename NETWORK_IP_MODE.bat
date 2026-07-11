@echo off
setlocal

rem AMS demo network helper
rem 1 = Static IP for direct AMS connection
rem 2 = DHCP automatic IP

set "IFACE=이더넷"
set "STATIC_IP=192.168.0.10"
set "STATIC_MASK=255.255.255.0"
set "STATIC_GATEWAY=none"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Requesting administrator permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo ==========================================
echo   AMS Network IP Mode
echo ==========================================
echo   Adapter : %IFACE%
echo.
echo   1. AMS STATIC  %STATIC_IP% / %STATIC_MASK%
echo   2. DHCP AUTO
echo   3. Show current IP
echo   0. Exit
echo.
set /p "CHOICE=Select: "

if "%CHOICE%"=="1" goto STATIC
if "%CHOICE%"=="2" goto DHCP
if "%CHOICE%"=="3" goto SHOW
if "%CHOICE%"=="0" goto END

echo Invalid selection.
goto END

:STATIC
echo.
echo Setting %IFACE% to AMS static IP...
netsh interface ip set address name="%IFACE%" static %STATIC_IP% %STATIC_MASK% %STATIC_GATEWAY%
netsh interface ip set dns name="%IFACE%" dhcp
echo.
echo Done. Current IP:
ipconfig | findstr /C:"Ethernet adapter" /C:"이더넷" /C:"IPv4" /C:"Subnet Mask" /C:"Default Gateway"
goto END

:DHCP
echo.
echo Setting %IFACE% to DHCP automatic IP...
netsh interface ip set address name="%IFACE%" dhcp
netsh interface ip set dns name="%IFACE%" dhcp
echo.
echo Done. Current IP:
ipconfig | findstr /C:"Ethernet adapter" /C:"이더넷" /C:"IPv4" /C:"Subnet Mask" /C:"Default Gateway"
goto END

:SHOW
echo.
ipconfig
goto END

:END
echo.
pause
endlocal
