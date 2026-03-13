"""ログ設定モジュール。

コンソール（stderr）とファイルへのデュアル出力ロガーを提供する。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str = "dify_loader", log_dir: str = "logs") -> logging.Logger:
    """アプリケーションロガーを初期化する。

    コンソール（stderr, INFO レベル）とファイル（DEBUG レベル）の
    2 つのハンドラを設定する。

    Args:
        name: ロガー名。
        log_dir: ログファイルの出力ディレクトリ。

    Returns:
        設定済みの Logger インスタンス。
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_handler = logging.FileHandler(
        log_path / f"{timestamp}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """既存のアプリケーションロガーを取得する。

    Returns:
        アプリケーションロガー。
    """
    return logging.getLogger("dify_loader")
