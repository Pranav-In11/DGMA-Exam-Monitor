#!/usr/bin/env python3
"""
DGMA Exam Monitor - GitHub Actions Worker
Runs on GitHub Actions with Indian proxy routing
Stores results in Google Sheets
Sends notifications via Google Apps Script
"""

import os
import re
import logging
from datetime import datetime

import requests
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dgma_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    'TELEGRAM_TOKEN': os.getenv('TELEGRAM_TOKEN'),
    'TELEGRAM_CHAT_ID': os.getenv('TELEGRAM_CHAT_ID'),
    'SHEET_ID': os.getenv('SHEET_ID'),
    'DGMA_USERNAME': os.getenv('DGMA_USERNAME'),
    'DGMA_PASSWORD': os.getenv('DGMA_PASSWORD'),
    'PROXY_URL': os.getenv('PROXY_URL'),
    'PORTAL_URL': 'https://exams.dgma.gov.in',
    'LOGIN_ACTION': 'https://exams.dgma.gov.in/j_security_check',
    'GAS_ENDPOINT': os.getenv('GAS_ENDPOINT')  # Optional: Google Apps Script webhook
}

class DGMABot:
    def __init__(self):
        self.session = requests.Session()

        # Set proxy if provided
        if CONFIG['PROXY_URL']:
            self.session.proxies = {
                'http': CONFIG['PROXY_URL'],
                'https': CONFIG['PROXY_URL']
            }
            logger.info(f"Using proxy: {CONFIG['PROXY_URL']}")

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def send_to_tg(self, message, msg_type='info'):
        """Send message to Telegram"""
        icons = {
            'info': '📌',
            'success': '✅',
            'warning': '⚠️',
            'error': '❌'
        }

        full_message = f"{icons.get(msg_type, '•')} {message}"

        try:
            url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN']}/sendMessage"
            requests.post(url, json={
                'chat_id': CONFIG['TELEGRAM_CHAT_ID'],
                'text': full_message,
                'parse_mode': 'HTML'
            }, timeout=10)
            logger.info(full_message)
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    def send_to_gas(self, data):
        """Send data to Google Apps Script endpoint"""
        if not CONFIG['GAS_ENDPOINT']:
            return

        try:
            requests.post(CONFIG['GAS_ENDPOINT'], json=data, timeout=10)
            logger.info("Data sent to Google Apps Script")
        except Exception as e:
            logger.error(f"GAS error: {e}")

    def append_to_sheet(self, data):
        """Append data to Google Sheet via Google Apps Script"""
        payload = {
            'action': 'append',
            'timestamp': datetime.now().isoformat(),
            'exam_date': data.get('exam_date', ''),
            'oral_link': data.get('oral_link', ''),
            'status': data.get('status', 'OK')
        }

        self.send_to_gas(payload)

    def solve_captcha(self, base64_image):
        """Solve captcha using OCR (online or local)"""
        try:
            # Try free online OCR first
            logger.info("Trying free OCR service...")

            if ',' in base64_image:
                base64_image = base64_image.split(',')[1]

            response = requests.post('https://api.ocr.space/parse', data={
                'base64Image': f'data:image/jpeg;base64,{base64_image}',
                'language': 'eng',
                'apikey': 'K87899142372222'  # Free demo key
            }, timeout=30)

            result = response.json()

            if not result.get('IsErroredOnProcessing') and result.get('ParsedText'):
                captcha = ''.join(c for c in result['ParsedText'] if c.isalnum())[:6].upper()
                if len(captcha) >= 4:
                    logger.info(f"OCR solved: {captcha}")
                    self.send_to_tg(f'OCR solved: {captcha}', 'success')
                    return captcha

            return None
        except Exception as e:
            logger.error(f"OCR error: {e}")
            return None

    def login(self):
        """Login to DGMA portal"""
        try:
            self.send_to_tg('🔐 Logging in...', 'info')
            logger.info("Fetching login page...")

            # Fetch login page
            response = self.session.get(CONFIG['LOGIN_ACTION'], timeout=15)

            # Extract captcha
            match = re.search(r'id="capt[a-z]*Img"[^>]*src="([^"]+)"', response.text, re.IGNORECASE)
            if not match:
                match = re.search(r'src="([^"]*captcha[^"]*)"', response.text, re.IGNORECASE)
            if not match:
                self.send_to_tg('❌ Captcha not found', 'error')
                return None

            captcha_b64 = match.group(1)
            self.send_to_tg('📸 Found captcha', 'info')

            # Solve captcha
            self.send_to_tg('🤖 Solving captcha...', 'info')
            captcha_text = self.solve_captcha(captcha_b64)

            if not captcha_text:
                self.send_to_tg('⚠️ OCR failed - cannot get captcha', 'warning')
                logger.warning("OCR failed, captcha solving skipped")
                # Try with empty/random
                captcha_text = 'ABCDEF'

            # Submit login
            self.send_to_tg('🔑 Submitting login...', 'info')

            payload = {
                'username': CONFIG['DGMA_USERNAME'],
                'password': CONFIG['DGMA_PASSWORD'],
                'verifyCode': captcha_text,
                'latitude': '0.0',
                'longitude': '0.0'
            }

            login_response = self.session.post(
                CONFIG['LOGIN_ACTION'],
                data=payload,
                allow_redirects=True,
                timeout=15
            )

            if any(x in login_response.text for x in ['Signout', 'logout', 'dashboard']):
                self.send_to_tg('✅ Login successful!', 'success')
                logger.info("Login successful")
                return login_response.text
            else:
                self.send_to_tg('❌ Login failed', 'error')
                logger.error("Login failed")
                return None

        except Exception as e:
            self.send_to_tg(f'❌ Login error: {e}', 'error')
            logger.error(f"Login error: {e}")
            return None

    def scrape(self, html=""):
        """Scrape exam date and oral link"""
        data = {}

        try:
            page_content = html or ""
            # Fetch dashboard if no HTML provided
            if not page_content:
                for url in [
                    f"{CONFIG['PORTAL_URL']}/candidateHome",
                    f"{CONFIG['PORTAL_URL']}/dashboard",
                    f"{CONFIG['PORTAL_URL']}/home"
                ]:
                    try:
                        response = self.session.get(url, timeout=10)
                        if response.status_code == 200:
                            page_content = response.text
                            break
                    except requests.RequestException:
                        continue

            # Find exam date
            for pattern in [
                r'exam\s*date[:\s]*([0-9\-\/\.]+)',
                r'scheduled\s*date[:\s]*([0-9\-\/\.]+)'
            ]:
                matches = re.findall(pattern, page_content, re.IGNORECASE)
                if matches:
                    data['exam_date'] = matches[-1]
                    logger.info(f"Found exam date: {data['exam_date']}")
                    break

            # Find oral link
            for pattern in [
                r'href=["\'](.*?oral.*?)["\']',
                r'href=["\'](.*?interview.*?)["\']'
            ]:
                matches = re.findall(pattern, page_content, re.IGNORECASE)
                if matches:
                    link = matches[-1]
                    if not link.startswith('http'):
                        link = CONFIG['PORTAL_URL'] + ('/' if not link.startswith('/') else '') + link
                    data['oral_link'] = link
                    logger.info(f"Found oral link: {data['oral_link']}")
                    break

        except Exception as e:
            logger.error(f"Scraping error: {e}")

        return data

    def run(self):
        """Run bot"""
        logger.info("="*60)
        logger.info(f"Starting DGMA check at {datetime.now()}")
        logger.info("="*60)

        self.send_to_tg('🤖 Starting exam check...', 'info')

        # Login
        html = self.login()
        if not html:
            self.send_to_tg('❌ Check failed - login error', 'error')
            return

        # Scrape
        self.send_to_tg('📄 Scraping dashboard...', 'info')
        data = self.scrape(html)

        # Save to sheet
        self.send_to_tg('💾 Saving to Google Sheet...', 'info')
        data['status'] = 'OK'
        self.append_to_sheet(data)

        self.send_to_tg('✅ Check completed', 'success')
        logger.info("Check completed successfully")

def test_bot():
    """Self-check for bot scrapers and helpers"""
    bot = DGMABot()
    sample_html = '''
    <html>
        <body>
            <img id="captchaImg" src="data:image/png;base64,ABC123" />
            <div>Exam Date: 20-10-2026</div>
            <a href="/portal/oralExamDetails">Oral Exam Link</a>
        </body>
    </html>
    '''
    data = bot.scrape(sample_html)
    assert data.get('exam_date') == '20-10-2026', f"Unexpected date: {data.get('exam_date')}"
    assert 'oralExamDetails' in data.get('oral_link', ''), f"Unexpected link: {data.get('oral_link')}"
    
    match = re.search(r'id="capt[a-z]*Img"[^>]*src="([^"]+)"', sample_html, re.IGNORECASE)
    assert match and match.group(1) == 'data:image/png;base64,ABC123'
    logger.info("Self-check passed!")

def main():
    import sys
    if '--test' in sys.argv or not CONFIG['DGMA_USERNAME']:
        logger.info("Running self-check...")
        test_bot()
        if '--test' in sys.argv:
            return

    logger.info("DGMA Bot starting...")

    # Validate config
    if not CONFIG['DGMA_USERNAME']:
        logger.error("DGMA_USERNAME not set")
        raise ValueError("Missing DGMA_USERNAME")

    if not CONFIG['DGMA_PASSWORD']:
        logger.error("DGMA_PASSWORD not set")
        raise ValueError("Missing DGMA_PASSWORD")

    bot = DGMABot()
    bot.run()

if __name__ == '__main__':
    main()
