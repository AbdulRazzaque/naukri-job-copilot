@echo off
echo ===================================================
echo Starting Google Chrome in Remote Debugging Mode
echo Port: 9222
echo Targeting: Naukri.com India (Gulf Redirect Blocked)
echo Profile Directory: C:\ChromeDebugProfile
echo ===================================================
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebugProfile" https://www.naukri.com/mnjuser/homepage
