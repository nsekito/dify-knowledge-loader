"""ファイルハッシュ計算モジュール。

SHA-256 によるファイルハッシュを提供し、差分検知に利用する。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

BUFFER_SIZE = 65536  # 64KB


def compute_sha256(file_path: str | Path) -> str:
    """ファイルの SHA-256 ハッシュを計算する。

    Args:
        file_path: ハッシュ対象のファイルパス。

    Returns:
        16 進数文字列の SHA-256 ハッシュ値。
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(BUFFER_SIZE)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()
