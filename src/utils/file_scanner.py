"""ファイル走査・フィルタリングモジュール。

指定ディレクトリから Markdown ファイルを検索し、
除外パターンでフィルタリングする。
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from src.utils.logger import get_logger


def scan_markdown_files(
    target_dir: str,
    recursive: bool = True,
    exclude_patterns: list[str] | None = None,
) -> list[Path]:
    """指定ディレクトリから Markdown ファイルを走査する。

    Args:
        target_dir: 走査対象のルートディレクトリパス。
        recursive: True の場合サブディレクトリも再帰的に探索する。
        exclude_patterns: 除外する glob パターンのリスト。

    Returns:
        対象ファイルの Path リスト（ソート済み）。

    Raises:
        FileNotFoundError: target_dir が存在しない場合。
    """
    logger = get_logger()
    base = Path(target_dir)

    if not base.exists():
        raise FileNotFoundError(f"対象ディレクトリが見つかりません: {target_dir}")
    if not base.is_dir():
        raise NotADirectoryError(f"ディレクトリではありません: {target_dir}")

    pattern = "**/*.md" if recursive else "*.md"
    all_files = sorted(base.glob(pattern))

    if not exclude_patterns:
        logger.info("対象ファイル: %d 件", len(all_files))
        return all_files

    filtered: list[Path] = []
    excluded_count = 0

    for f in all_files:
        rel = f.relative_to(base).as_posix()
        if _matches_any_pattern(rel, exclude_patterns):
            excluded_count += 1
            logger.debug("除外: %s", rel)
        else:
            filtered.append(f)

    logger.info(
        "対象ファイル: %d 件（除外: %d 件）", len(filtered), excluded_count
    )
    return filtered


def _matches_any_pattern(relative_path: str, patterns: list[str]) -> bool:
    """相対パスがいずれかの除外パターンに一致するか判定する。

    Args:
        relative_path: target_dir からの相対パス（POSIX 形式）。
        patterns: glob 形式の除外パターンリスト。

    Returns:
        いずれかのパターンに一致すれば True。
    """
    for pat in patterns:
        if fnmatch.fnmatch(relative_path, pat):
            return True
    return False
