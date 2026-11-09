import asyncio
import os
from playwright.async_api import async_playwright

async def upload_to_naukri():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        context = browser.contexts[0]
        page = [p for p in context.pages if 'naukri.com' in p.url][0]
        
        file_path = os.path.abspath('backend/Abdul_Razzaque_India.pdf')
        print(f"Uploading file: {file_path}")
        
        cv_input = page.locator('#attachCV')
        await cv_input.set_input_files(file_path)
        print("Set input files on #attachCV! Waiting for upload processing...")
        await asyncio.sleep(5)
        
        # Verify notification
        success_info = await page.evaluate("""() => {
            const toast = document.querySelector('.toast, .success, .msg, .notification, [class*="success"], [class*="toast"]');
            return toast ? toast.innerText : 'No explicit toast';
        }""")
        print("Notification/Toast after upload:", success_info)
        
        # Take screenshot of Naukri profile page
        await page.screenshot(path='backend/screenshots/naukri_cv_uploaded_final.png')
        print("Saved screenshot to backend/screenshots/naukri_cv_uploaded_final.png")

if __name__ == '__main__':
    asyncio.run(upload_to_naukri())

