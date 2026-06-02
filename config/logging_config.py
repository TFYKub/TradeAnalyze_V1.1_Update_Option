import logging
import os

LOG_DIR = "logs"

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
    handlers=[
        logging.FileHandler(
            f"{LOG_DIR}/trade_analyze.log",
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("TradeAnalyze")
