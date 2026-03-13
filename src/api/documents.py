"""ドキュメント操作 API モジュール。

Dify ナレッジベースのドキュメント CRUD とインデクシング状態取得を提供する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.api.client import DifyClient
from src.config import ChunkingConfig
from src.models.document import DocumentInfo, IndexingStatusInfo
from src.utils.logger import get_logger


class DocumentsApi:
    """ドキュメント操作を行う API ラッパー。"""

    def __init__(self, client: DifyClient, dataset_id: str) -> None:
        """初期化する。

        Args:
            client: Dify API クライアント。
            dataset_id: 対象ナレッジベース ID。
        """
        self._client = client
        self._dataset_id = dataset_id
        self._logger = get_logger()

    def create_by_file(
        self, file_path: Path, chunking: ChunkingConfig
    ) -> dict[str, Any]:
        """ファイルからドキュメントを作成する。

        Args:
            file_path: アップロードする Markdown ファイルのパス。
            chunking: チャンク分割設定。

        Returns:
            API レスポンス（document_id, batch 等を含む）。
        """
        data_payload = self._build_data_payload(chunking)

        with open(file_path, "rb") as f:
            files = {
                "file": (file_path.name, f, "text/markdown"),
            }
            resp = self._client.post_multipart(
                f"/v1/datasets/{self._dataset_id}/document/create-by-file",
                files=files,
                data={"data": json.dumps(data_payload)},
            )

        return resp

    def update_by_file(
        self, document_id: str, file_path: Path, chunking: ChunkingConfig
    ) -> dict[str, Any]:
        """既存ドキュメントをファイルで更新する。

        Args:
            document_id: 更新対象のドキュメント ID。
            file_path: 新しい Markdown ファイルのパス。
            chunking: チャンク分割設定。

        Returns:
            API レスポンス。
        """
        data_payload = self._build_data_payload(chunking)

        with open(file_path, "rb") as f:
            files = {
                "file": (file_path.name, f, "text/markdown"),
            }
            resp = self._client.post_multipart(
                f"/v1/datasets/{self._dataset_id}/documents/{document_id}/update-by-file",
                files=files,
                data={"data": json.dumps(data_payload)},
            )

        return resp

    def list_documents(
        self, page: int = 1, limit: int = 20
    ) -> tuple[list[DocumentInfo], bool, int]:
        """ドキュメント一覧を取得する。

        Args:
            page: ページ番号。
            limit: 1 ページあたりの件数。

        Returns:
            (ドキュメントリスト, has_more, total) のタプル。
        """
        resp = self._client.get(
            f"/v1/datasets/{self._dataset_id}/documents",
            params={"page": page, "limit": limit},
        )

        docs = [
            DocumentInfo(
                id=d["id"],
                name=d.get("name", ""),
                indexing_status=d.get("indexing_status", ""),
                enabled=d.get("enabled", True),
                created_at=d.get("created_at", 0),
            )
            for d in resp.get("data", [])
        ]

        return docs, resp.get("has_more", False), resp.get("total", 0)

    def list_all_documents(self, limit: int = 20) -> list[DocumentInfo]:
        """全ドキュメントをページネーション込みで取得する。

        Args:
            limit: 1 ページあたりの件数。

        Returns:
            全ドキュメントのリスト。
        """
        all_docs: list[DocumentInfo] = []
        page = 1

        while True:
            docs, has_more, total = self.list_documents(page=page, limit=limit)
            all_docs.extend(docs)
            self._logger.debug(
                "ドキュメント一覧取得: page=%d, 取得=%d, 合計=%d",
                page, len(docs), total,
            )
            if not has_more:
                break
            page += 1

        return all_docs

    def get_indexing_status(self, batch: str) -> list[IndexingStatusInfo]:
        """バッチのインデクシング状態を取得する。

        Args:
            batch: バッチ ID。

        Returns:
            インデクシング状態のリスト。
        """
        resp = self._client.get(
            f"/v1/datasets/{self._dataset_id}/documents/{batch}/indexing-status"
        )

        return [
            IndexingStatusInfo(
                id=item.get("id", ""),
                indexing_status=item.get("indexing_status", ""),
                completed_segments=item.get("completed_segments", 0),
                total_segments=item.get("total_segments", 0),
                error=item.get("error"),
            )
            for item in resp.get("data", [])
        ]

    def delete_document(self, document_id: str) -> dict:
        """ドキュメントを削除する。

        Args:
            document_id: 削除対象のドキュメント ID。

        Returns:
            API レスポンス。
        """
        return self._client.delete(
            f"/v1/datasets/{self._dataset_id}/documents/{document_id}"
        )

    def _build_data_payload(self, chunking: ChunkingConfig) -> dict[str, Any]:
        """チャンク設定から API の data パラメータを構築する。

        Args:
            chunking: チャンク分割設定。

        Returns:
            API に送信する data パラメータの辞書。
        """
        if chunking.mode == "custom":
            return {
                "indexing_technique": chunking.indexing_technique,
                "process_rule": {
                    "mode": "custom",
                    "rules": {
                        "pre_processing_rules": [
                            {
                                "id": "remove_extra_spaces",
                                "enabled": chunking.custom.remove_extra_spaces,
                            },
                            {
                                "id": "remove_urls_emails",
                                "enabled": chunking.custom.remove_urls_emails,
                            },
                        ],
                        "segmentation": {
                            "separator": chunking.custom.separator,
                            "max_tokens": chunking.custom.max_tokens,
                        },
                    },
                },
            }

        return {
            "indexing_technique": chunking.indexing_technique,
            "process_rule": {
                "mode": "automatic",
            },
        }
