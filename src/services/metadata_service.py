"""メタデータフィールド同期・付与ロジック。

metadata.yaml のフィールド定義を Dify ナレッジベースに同期し、
ドキュメントへのメタデータ付与データを構築する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.api.metadata import MetadataApi
from src.config import MetadataConfig
from src.models.document import MetadataFieldInfo
from src.utils.logger import get_logger


class MetadataService:
    """メタデータフィールドの同期と値の解決を行うサービス。"""

    def __init__(self, metadata_api: MetadataApi, config: MetadataConfig) -> None:
        """初期化する。

        Args:
            metadata_api: メタデータ API ラッパー。
            config: メタデータ設定。
        """
        self._api = metadata_api
        self._config = config
        self._logger = get_logger()
        self._field_map: dict[str, str] = {}

    @property
    def field_map(self) -> dict[str, str]:
        """フィールド名から ID へのマッピングを返す。"""
        return self._field_map

    def sync_fields(self) -> dict[str, str]:
        """metadata.yaml のフィールド定義をナレッジベースに同期する。

        既存フィールドと比較し、不足分を作成する。
        全フィールドの {name → id} マッピングを返す。

        Returns:
            フィールド名から ID へのマッピング辞書。
        """
        self._logger.info("メタデータフィールドを同期中...")

        existing = self._api.list_fields()
        existing_map = {f.name: f for f in existing}

        self._logger.debug(
            "既存フィールド: %s",
            ", ".join(f.name for f in existing) if existing else "(なし)",
        )

        for field_def in self._config.fields:
            if field_def.name in existing_map:
                self._field_map[field_def.name] = existing_map[field_def.name].id
                self._logger.debug(
                    "フィールド '%s' は既に存在（ID: %s）",
                    field_def.name,
                    existing_map[field_def.name].id,
                )
            else:
                created = self._api.create_field(field_def.name, field_def.type)
                self._field_map[field_def.name] = created.id
                self._logger.info(
                    "フィールド '%s' を作成（ID: %s, type: %s）",
                    field_def.name,
                    created.id,
                    field_def.type,
                )

        self._logger.info(
            "メタデータフィールド同期完了（合計: %d フィールド）",
            len(self._field_map),
        )
        return self._field_map

    def list_fields(self) -> list[MetadataFieldInfo]:
        """ナレッジベースのメタデータフィールド一覧を取得する。

        Returns:
            MetadataFieldInfo のリスト。
        """
        return self._api.list_fields()

    def build_metadata_list(
        self,
        file_path: Path,
        target_dir: str,
        cli_meta_overrides: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """1 ドキュメント用のメタデータリストを構築する。

        auto:filename / auto:relative_path を解決し、
        CLI の --meta オプションによる上書きを適用する。

        Args:
            file_path: 対象ファイルの絶対パス。
            target_dir: ファイル走査のルートディレクトリ。
            cli_meta_overrides: CLI --meta オプションで指定された上書き値。

        Returns:
            API に送信するメタデータリスト。
        """
        overrides = cli_meta_overrides or {}
        target = Path(target_dir)
        metadata_list: list[dict[str, Any]] = []

        for field_def in self._config.fields:
            if field_def.name not in self._field_map:
                continue

            field_id = self._field_map[field_def.name]
            value = self._resolve_value(
                field_def.name, file_path, target, overrides
            )

            metadata_list.append({
                "id": field_id,
                "name": field_def.name,
                "value": value,
            })

        return metadata_list

    def apply_metadata(
        self,
        document_id: str,
        metadata_list: list[dict[str, Any]],
    ) -> None:
        """ドキュメントにメタデータを付与する。

        Args:
            document_id: 対象ドキュメント ID。
            metadata_list: メタデータリスト。
        """
        if not metadata_list:
            return

        self._api.update_documents_metadata([
            {
                "document_id": document_id,
                "metadata_list": metadata_list,
            }
        ])

    def _resolve_value(
        self,
        field_name: str,
        file_path: Path,
        target_dir: Path,
        overrides: dict[str, str],
    ) -> str:
        """メタデータ値を解決する。

        優先順位: CLI 上書き > auto 解決 > 設定ファイルの固定値

        Args:
            field_name: フィールド名。
            file_path: 対象ファイルパス。
            target_dir: ルートディレクトリ。
            overrides: CLI 上書き値。

        Returns:
            解決されたメタデータ値。
        """
        if field_name in overrides:
            return overrides[field_name]

        raw_value = self._config.values.get(field_name, "")

        if raw_value == "auto:filename":
            return file_path.name
        elif raw_value == "auto:filename_stem":
            return file_path.stem
        elif raw_value == "auto:parent_dir":
            return file_path.parent.name
        elif raw_value == "auto:relative_path":
            try:
                return file_path.relative_to(target_dir).as_posix()
            except ValueError:
                return file_path.name
        else:
            return str(raw_value)
