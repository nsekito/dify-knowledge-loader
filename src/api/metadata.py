"""メタデータ操作 API モジュール。

ナレッジベースのメタデータフィールド管理と、
ドキュメントへのメタデータ付与を提供する。
"""

from __future__ import annotations

from typing import Any

from src.api.client import DifyClient
from src.models.document import MetadataFieldInfo
from src.utils.logger import get_logger


class MetadataApi:
    """メタデータ操作を行う API ラッパー。"""

    def __init__(self, client: DifyClient, dataset_id: str) -> None:
        """初期化する。

        Args:
            client: Dify API クライアント。
            dataset_id: 対象ナレッジベース ID。
        """
        self._client = client
        self._dataset_id = dataset_id
        self._logger = get_logger()

    def list_fields(self) -> list[MetadataFieldInfo]:
        """メタデータフィールド一覧を取得する。

        Returns:
            MetadataFieldInfo のリスト。
        """
        resp = self._client.get(f"/v1/datasets/{self._dataset_id}/metadata")

        return [
            MetadataFieldInfo(
                id=f["id"],
                name=f["name"],
                type=f["type"],
                use_count=f.get("use_count", 0),
            )
            for f in resp.get("doc_metadata", [])
        ]

    def create_field(self, name: str, field_type: str) -> MetadataFieldInfo:
        """メタデータフィールドを新規作成する。

        Args:
            name: フィールド名。
            field_type: フィールド型（"string" / "number" / "time"）。

        Returns:
            作成されたフィールドの情報。
        """
        resp = self._client.post_json(
            f"/v1/datasets/{self._dataset_id}/metadata",
            json_data={"type": field_type, "name": name},
        )

        return MetadataFieldInfo(
            id=resp["id"],
            name=resp["name"],
            type=resp["type"],
        )

    def update_field_name(self, metadata_id: str, new_name: str) -> dict:
        """メタデータフィールド名を更新する。

        Args:
            metadata_id: フィールド ID。
            new_name: 新しいフィールド名。

        Returns:
            API レスポンス。
        """
        return self._client.patch(
            f"/v1/datasets/{self._dataset_id}/metadata/{metadata_id}",
            json_data={"name": new_name},
        )

    def delete_field(self, metadata_id: str) -> dict:
        """メタデータフィールドを削除する。

        Args:
            metadata_id: 削除対象のフィールド ID。

        Returns:
            API レスポンス。
        """
        return self._client.delete(
            f"/v1/datasets/{self._dataset_id}/metadata/{metadata_id}"
        )

    def update_documents_metadata(
        self, operation_data: list[dict[str, Any]]
    ) -> dict:
        """ドキュメントにメタデータを付与する。

        Args:
            operation_data: メタデータ付与の操作データリスト。
                各要素は {"document_id": ..., "metadata_list": [...]} の形式。

        Returns:
            API レスポンス。
        """
        return self._client.post_json(
            f"/v1/datasets/{self._dataset_id}/documents/metadata",
            json_data={"operation_data": operation_data},
        )
