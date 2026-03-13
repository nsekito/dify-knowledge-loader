"""設定ファイル読み込みモジュール。

config/ ディレクトリ配下の YAML ファイルを読み込み、
型付き設定オブジェクトとして提供する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ConnectionConfig:
    """Dify サーバ接続設定。"""

    base_url: str
    api_key: str
    dataset_id: str
    target_dir: str
    recursive: bool = True
    exclude_patterns: list[str] = field(default_factory=list)
    upload_interval_sec: float = 1.0


@dataclass
class CustomChunkingConfig:
    """カスタムチャンク分割の詳細設定。"""

    separator: str = "\\n"
    max_tokens: int = 500
    remove_extra_spaces: bool = True
    remove_urls_emails: bool = False


@dataclass
class ChunkingConfig:
    """チャンク分割設定。"""

    indexing_technique: str = "high_quality"
    mode: str = "automatic"
    custom: CustomChunkingConfig = field(default_factory=CustomChunkingConfig)


@dataclass
class MetadataFieldDef:
    """メタデータフィールド定義。"""

    name: str
    type: str


@dataclass
class MetadataConfig:
    """メタデータ設定。"""

    fields: list[MetadataFieldDef] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)


@dataclass
class AppConfig:
    """アプリケーション全体の設定。"""

    connection: ConnectionConfig
    chunking: ChunkingConfig
    metadata: MetadataConfig


def load_config(config_dir: str = "./config") -> AppConfig:
    """設定ディレクトリから全設定ファイルを読み込む。

    Args:
        config_dir: 設定ファイルが格納されたディレクトリパス。

    Returns:
        統合された AppConfig オブジェクト。

    Raises:
        FileNotFoundError: 必須の設定ファイルが見つからない場合。
        ValueError: 設定ファイルの内容が不正な場合。
    """
    base = Path(config_dir)

    connection = _load_connection(base / "connection.yaml")
    chunking = _load_chunking(base / "chunking.yaml")
    metadata = _load_metadata(base / "metadata.yaml")

    return AppConfig(connection=connection, chunking=chunking, metadata=metadata)


def _load_yaml(path: Path) -> dict:
    """YAML ファイルを読み込んで辞書として返す。

    Args:
        path: YAML ファイルのパス。

    Returns:
        パース済みの辞書。

    Raises:
        FileNotFoundError: ファイルが存在しない場合。
    """
    if not path.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {path}\n"
            f"  → {path.stem}.yaml.example をコピーして作成してください。\n"
            f"  → copy {path.stem}.yaml.example {path.stem}.yaml"
        )
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"設定ファイルの形式が不正です（辞書形式である必要があります）: {path}")
    return data


def _load_connection(path: Path) -> ConnectionConfig:
    """connection.yaml を読み込む。

    Args:
        path: connection.yaml のパス。

    Returns:
        ConnectionConfig オブジェクト。

    Raises:
        ValueError: 必須フィールドが不足している場合。
    """
    data = _load_yaml(path)

    required_keys = ["base_url", "api_key", "dataset_id", "target_dir"]
    missing = [k for k in required_keys if not data.get(k)]
    if missing:
        raise ValueError(
            f"connection.yaml に必須項目が不足しています: {', '.join(missing)}"
        )

    return ConnectionConfig(
        base_url=data["base_url"].rstrip("/"),
        api_key=data["api_key"],
        dataset_id=data["dataset_id"],
        target_dir=data["target_dir"],
        recursive=data.get("recursive", True),
        exclude_patterns=data.get("exclude_patterns", []) or [],
        upload_interval_sec=float(data.get("upload_interval_sec", 1.0)),
    )


def _load_chunking(path: Path) -> ChunkingConfig:
    """chunking.yaml を読み込む。

    Args:
        path: chunking.yaml のパス。

    Returns:
        ChunkingConfig オブジェクト。
    """
    data = _load_yaml(path)

    custom_data = data.get("custom", {}) or {}
    pre = custom_data.get("pre_processing", {}) or {}

    custom = CustomChunkingConfig(
        separator=custom_data.get("separator", "\\n"),
        max_tokens=int(custom_data.get("max_tokens", 500)),
        remove_extra_spaces=pre.get("remove_extra_spaces", True),
        remove_urls_emails=pre.get("remove_urls_emails", False),
    )

    return ChunkingConfig(
        indexing_technique=data.get("indexing_technique", "high_quality"),
        mode=data.get("mode", "automatic"),
        custom=custom,
    )


def _load_metadata(path: Path) -> MetadataConfig:
    """metadata.yaml を読み込む。

    Args:
        path: metadata.yaml のパス。

    Returns:
        MetadataConfig オブジェクト。
    """
    data = _load_yaml(path)

    fields_raw = data.get("fields", []) or []
    fields = [
        MetadataFieldDef(name=f["name"], type=f["type"])
        for f in fields_raw
        if "name" in f and "type" in f
    ]

    values = data.get("values", {}) or {}

    return MetadataConfig(fields=fields, values=values)
