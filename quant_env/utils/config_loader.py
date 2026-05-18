import os
from dotenv import load_dotenv

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
load_dotenv(os.path.join(project_root, '.env'))

def get_env(key, default=None):
    return os.getenv(key, default)

def load_config():
    """Return a dict of configuration loaded from environment variables."""
    return {
        'TELEGRAM_TOKEN': get_env('TELEGRAM_TOKEN', ''),
        'TELEGRAM_CHAT_ID': get_env('TELEGRAM_CHAT_ID', ''),
    }