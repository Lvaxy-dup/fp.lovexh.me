from pathlib import Path
import os
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
v = {**dotenv_values(ROOT.parent / 'deepseek.txt'), **dotenv_values(ROOT / '.env'), **os.environ}
RUNTIME = Path(v.get('TRAVEL_DATA_DIR') or ROOT / '.runtime').expanduser().resolve()
RUNTIME.mkdir(parents=True,exist_ok=True)
COOKIE_SECURE = v.get('TRAVEL_COOKIE_SECURE','false').lower()=='true'
AUTO_BACKUP = v.get('TRAVEL_AUTO_BACKUP','true').lower()=='true'
API_BASE = v.get('OPENAI_BASE_URL', 'https://api.deepseek.com').rstrip('/')
API_KEY = v.get('OPENAI_API_KEY', '')
MODEL = v.get('AGENT_MODEL', 'deepseek-v4-flash')
OCR_TOKEN = v.get('PADDLEOCR_API_TOKEN', '')
OCR_URL = 'https://paddleocr.aistudio-app.com/api/v2/ocr/jobs'
MAX_PAGES = 30
MAX_BYTES = 20 * 1024 * 1024
