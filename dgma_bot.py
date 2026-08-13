import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup

class ProxyRotator:
    def __init__(self):
        self.proxies = []
        self.sources = [
            "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&country=in&timeout=600",
        ]

    def refresh_proxies(self):
        """Fetch fresh Indian proxies."""
        new_proxies = []
        for url in self.sources:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    lines = response.text.splitlines()
                    new_proxies.extend(lines)
            except Exception as e:
                print(f"Error fetching proxies from {url}: {e}")
        
        self.proxies = list(set([p.strip() for p in new_proxies if p.strip()]))
        random.shuffle(self.proxies)
        print(f"Refreshed {len(self.proxies)} proxies.")

    def get_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies.pop(0)
        # Ensure it has the protocol
        if not proxy.startswith('http'):
            proxy = f"http://{proxy}"
        return {"http": proxy, "https": proxy}

class DGMABot:
    def __init__(self, telegram_token, chat_id, username, password):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.rotator = ProxyRotator()
        self.rotator.refresh_proxies()
        
        # Credentials & Config
        self.tg_token = telegram_token
        self.chat_id = chat_id
        self.username = username
        self.password = password
        self.base_url = "https://exams.dgma.gov.in"

    def send_tg_message(self, text):
        """Send a standard text message to Telegram."""
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        try:
            requests.post(url, json={'chat_id': self.chat_id, 'text': text})
        except Exception as e:
            print(f"Telegram MSG Error: {e}")

    def send_tg_photo_and_wait(self, base64_data):
        """Send Captcha image to Telegram and wait for manual user input."""
        import base64
        url = f"https://api.telegram.org/bot{self.tg_token}/sendPhoto"
        
        # Strip data URI prefix if present
        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]
            
        img_data = base64.b64decode(base64_data)
        
        try:
            # Send the photo
            requests.post(
                url, 
                data={'chat_id': self.chat_id, 'caption': 'Please reply with the Captcha code:'},
                files={'photo': ('captcha.jpg', img_data, 'image/jpeg')}
            )
            
            # Poll for the user's response
            print("Waiting for user to reply on Telegram...")
            updates_url = f"https://api.telegram.org/bot{self.tg_token}/getUpdates"
            
            # Get current update ID to ignore old messages
            resp = requests.get(updates_url).json()
            last_update_id = resp['result'][-1]['update_id'] if resp.get('result') else 0
            
            while True:
                time.sleep(3) # Check every 3 seconds
                resp = requests.get(f"{updates_url}?offset={last_update_id + 1}").json()
                if resp.get('result'):
                    for update in resp['result']:
                        if 'message' in update and 'text' in update['message']:
                            captcha_text = update['message']['text'].strip()
                            self.send_tg_message(f"Received Captcha: {captcha_text}")
                            return captcha_text
                        last_update_id = update['update_id']
        except Exception as e:
            print(f"Telegram Photo/Polling Error: {e}")
            return input("Enter Captcha manually in CLI: ")

    def solve_captcha(self, base64_image):
        """Try online OCR first, fallback to manual Telegram verification."""
        try:
            print("Trying free OCR service...")[cite: 1]
            clean_b64 = base64_image.split(',')[1] if ',' in base64_image else base64_image
            response = requests.post('https://api.ocr.space/parse', data={
                'base64Image': f'data:image/jpeg;base64,{clean_b64}',
                'language': 'eng',
                'apikey': 'helloworld' # Replace with actual API key if available
            }, timeout=30)
            
            result = response.json()
            if not result.get('IsErroredOnProcessing') and result.get('ParsedText'):
                captcha = ''.join(c for c in result['ParsedText'] if c.isalnum())[:6].upper()
                if len(captcha) >= 4:
                    self.send_tg_message(f"OCR automatically solved Captcha: {captcha}")[cite: 1]
                    return captcha
        except Exception as e:
            print(f"OCR error: {e}")

        # Fallback to Manual Telegram Verification
        self.send_tg_message("OCR Failed. Manual verification required.")
        return self.send_tg_photo_and_wait(base64_image)

    def login(self, max_retries=10):
        """Execute Login with automatic proxy retry and a direct connection fallback."""
        login_url = f"{self.base_url}/j_security_check"

        # --- SAFEGUARD 1: Proxy Retry Loop ---
        for attempt in range(1, max_retries + 1):
            proxy = self.rotator.get_proxy()
            
            # If we run out of proxies, refresh the pool
            if not proxy:
                print("Proxy list exhausted. Refreshing proxies...")
                self.rotator.refresh_proxies()
                proxy = self.rotator.get_proxy()

            self.session.proxies = proxy
            print(f"[Attempt {attempt}/{max_retries}] Trying proxy: {proxy.get('http')}")

            try:
                # Load login page to get Captcha (Connect timeout: 5s, Read timeout: 12s)
                resp = self.session.get(login_url, timeout=(5, 12))
                
                if resp.status_code != 200:
                    print(f"Bad status code {resp.status_code}, trying next proxy...")
                    continue

                # Find base64 image
                match = re.search(r'id="capt[a-z]*Img"[^>]*src="([^"]+)"', resp.text, re.IGNORECASE)
                if not match:
                    match = re.search(r'src="([^"]*captcha[^"]*)"', resp.text, re.IGNORECASE)
                
                if not match:
                    print("Captcha image not found on page, trying next proxy...")
                    continue
                    
                captcha_b64 = match.group(1)
                captcha_text = self.solve_captcha(captcha_b64)

                if not captcha_text:
                    print("Could not get Captcha text, retrying...")
                    continue

                # Submit Login
                payload = {
                    'username': self.username,
                    'password': self.password,
                    'verifyCode': captcha_text,
                    'latitude': '0.0',
                    'longitude': '0.0'
                }
                
                login_resp = self.session.post(login_url, data=payload, allow_redirects=True, timeout=(5, 15))
                
                # Check if login page redirected to homepage or logged in
                if login_resp.url == f"{self.base_url}/homepage" or "logout" in login_resp.text.lower() or "dashboard" in login_resp.text.lower():
                    self.send_tg_message("✅ Login Successful! Redirected to homepage.")
                    return True
                else:
                    print("Login form submission failed (Invalid credentials/captcha), retrying...")
                    continue

            except (requests.exceptions.Timeout, requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
                print(f"Proxy failed ({type(e).__name__}). Switching proxy...")
                continue
            except Exception as e:
                print(f"Unexpected error during login attempt: {e}")
                continue

        # --- SAFEGUARD 2: Direct Connection Fallback ---
        print("All proxy attempts failed. Attempting direct connection without proxy...")
        self.session.proxies = {} # Clear proxies
        
        try:
            resp = self.session.get(login_url, timeout=(5, 15))
            if resp.status_code == 200:
                match = re.search(r'id="capt[a-z]*Img"[^>]*src="([^"]+)"', resp.text, re.IGNORECASE)
                if not match:
                    match = re.search(r'src="([^"]*captcha[^"]*)"', resp.text, re.IGNORECASE)
                
                if match:
                    captcha_b64 = match.group(1)
                    captcha_text = self.solve_captcha(captcha_b64)

                    if captcha_text:
                        payload = {
                            'username': self.username,
                            'password': self.password,
                            'verifyCode': captcha_text,
                            'latitude': '0.0',
                            'longitude': '0.0'
                        }
                        
                        login_resp = self.session.post(login_url, data=payload, allow_redirects=True, timeout=(5, 15))
                        
                        if login_resp.url == f"{self.base_url}/homepage" or "logout" in login_resp.text.lower() or "dashboard" in login_resp.text.lower():
                            self.send_tg_message("✅ Login Successful on Direct Connection!")
                            return True
        except Exception as e:
            print(f"Direct connection fallback also failed: {e}")

        # Total Failure
        self.send_tg_message("❌ Failed to log in after multiple proxy attempts AND direct fallback.")
        return False

    def check_oral_updates(self):
        """Scrape the Oral Exam Updates page."""
        updates_url = f"{self.base_url}/oralExamUpdates"
        resp = self.session.get(updates_url, timeout=15)
        
        if resp.status_code != 200:
            self.send_tg_message("Failed to load Oral Exam Updates page.")
            return

        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Check if the "No Oral Examination" banner is present
        if soup.find(string=re.compile("No Oral Examination Scheduled Today", re.I)):
            self.send_tg_message("ℹ️ No Oral Examination Scheduled Today.")
            return

        # Scrape specific elements
        try:
            # Helper function to find a header div and grab the value div below it
            def get_card_value(header_text):
                header_div = soup.find('div', string=re.compile(header_text, re.I))
                if header_div:
                    val_div = header_div.find_next_sibling('div', class_='fs-5')
                    return val_div.text.strip() if val_div else "N/A"
                return "N/A"

            alloc_date = get_card_value("Allocated Date")
            grade = get_card_value("Grade")
            function = get_card_value("Function")
            
            # Check for Link Status
            meeting_status = "Not Found"
            if soup.find('span', string=re.compile("Link will be provided", re.I)):
                meeting_status = "⏳ Link will be provided (Pending)"
            elif soup.find('a', string=re.compile("Join", re.I)):
                # If a link actually exists
                link_tag = soup.find('a', string=re.compile("Join", re.I))
                meeting_status = f"✅ Available: {link_tag.get('href')}"

            # Format and send report
            report = (
                "🎯 **Oral Exam Update**\n\n"
                f"📅 **Allocated Date:** {alloc_date}\n"
                f"🎓 **Grade:** {grade}\n"
                f"⚙️ **Function:** {function}\n"
                f"🔗 **Meeting Link:** {meeting_status}"
            )
            
            print(report)
            self.send_tg_message(report)

        except Exception as e:
            self.send_tg_message(f"Error parsing HTML: {e}")

# --- Execution Entry Point ---
if __name__ == "__main__":
    # Configure your parameters here
    TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
    CHAT_ID = "YOUR_CHAT_ID"
    USERNAME = "YOUR_USERNAME"
    PASSWORD = "YOUR_PASSWORD"
    
    bot = DGMABot(TELEGRAM_TOKEN, CHAT_ID, USERNAME, PASSWORD)
    
    if bot.login():
        bot.check_oral_updates()
