"""データクラス定義モジュール。

アップロード結果・ドキュメント情報・状態管理に使用するデータクラスを定義する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class UploadStatus(Enum):
    """アップロード結果のステータス。"""

    SUCCESS = "成功"
    FAILED = "失敗"
    SKIPPED = "スキップ"


@dataclass
class UploadResult:
    """1 ファイルのアップロード結果を保持する。"""

    relative_path: str
    document_id: str = ""
    batch: str = ""
    metadata_applied: bool = False
    status: UploadStatus = UploadStatus.SUCCESS
    error_message: str = ""


@dataclass
class DocumentInfo:
    """Dify 上のドキュメント情報。"""

    id: str
    name: str
    indexing_status: str = ""
    enabled: bool = True
    created_at: int = 0


@dataclass
class FileState:
    """1 ファイルの状態管理情報。"""

    document_id: str
    hash: str
    uploaded_at: str


@dataclass
class MetadataFieldDef:
    """メタデータフィールドの定義。"""

    name: str
    type: str


@dataclass
class MetadataFieldInfo:
    """Dify 上のメタデータフィールド情報（ID 付き）。"""

    id: str
    name: str
    type: str
    use_count: int = 0


@dataclass
class IndexingStatusInfo:
    """インデクシング状態の情報。"""

    id: str
    indexing_status: str
    completed_segments: int = 0
    total_segments: int = 0
    error: str | None = None
