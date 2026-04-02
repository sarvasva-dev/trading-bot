@echo off
echo --- Bulkbeat TV Git Push Helper ---
echo.

:: 1. Initialize Git if not exists
if not exist .git (
    echo Initializing Git repository...
    git init
)

:: 2. Set Local Config (Does not affect your global settings)
echo Configuring local user...
git config user.email "trader@example.com"
git config user.name "Bulkbeat TV"

:: 3. Prepare Files
echo Staging files...
git add .

:: 4. Commit
echo Creating commit...
git commit -m "Initialize Bulkbeat TV v1.0: AI-powered Intelligence Engine"

:: 5. Set Branch to main
echo Setting branch to main...
git branch -M main

:: 6. Set Remote
echo Adding remote origin...
git remote remove origin >nul 2>&1
git remote add origin https://github.com/sitekraft/Trading-bot.git

:: 7. Push
echo.
echo ===================================================
echo IMPORTANT: If prompted, please login to GitHub.
echo ===================================================
echo.
git push -u origin main --force

echo.
echo Process complete! Press any key to exit.
pause >nul
