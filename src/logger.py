import logging
import os
import sys
from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "app.log")

_fmt = "%(asctime)s [%(levelname)s] %(message)s"
_datefmt = "%Y-%m-%dT%H:%M:%S"

logger = logging.getLogger("url_shortener")
logger.setLevel(LOG_LEVEL)

if not logger.handlers:
    _stream = logging.StreamHandler(sys.stdout)
    _stream.setFormatter(logging.Formatter(_fmt, _datefmt))
    logger.addHandler(_stream)

    _file = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _file.setFormatter(logging.Formatter(_fmt, _datefmt))
    logger.addHandler(_file)
