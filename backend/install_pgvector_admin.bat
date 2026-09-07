@echo off
:: Batch script to copy pgvector files to PostgreSQL 18 with Admin elevation
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrative privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set SRC=C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI\backend\pgvector_dist
set PG_DEST=C:\Program Files\PostgreSQL\18

echo Copying vector.dll to %PG_DEST%\lib...
copy /Y "%SRC%\lib\vector.dll" "%PG_DEST%\lib\"

echo Copying extensions to %PG_DEST%\share\extension...
xcopy /Y /E /I "%SRC%\share\extension\*" "%PG_DEST%\share\extension\"

if exist "%SRC%\include" (
    echo Copying includes to %PG_DEST%\include...
    xcopy /Y /E /I "%SRC%\include\*" "%PG_DEST%\include\"
)

echo.
echo ========================================================
echo pgvector files successfully installed into PostgreSQL 18!
echo ========================================================
pause
