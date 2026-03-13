"""差分更新ロジック。

前回のアップロード状態（state/upload_state.json）とファイルハッシュを比較し、
変更・新規ファイルのみを効率的にアップロードする。
"""

from __future__ import annotations

import json
import os
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.api.client import DifyApiError
from src.api.documents import DocumentsApi
from src.config import AppConfig
from src.models.document import UploadResult, UploadStatus
from src.services.metadata_service import MetadataService
from src.utils.file_scanner import scan_markdown_files
from src.utils.hash import compute_sha256
from src.utils.logger import get_logger

STATE_DIR = "state"
STATE_FILE = "upload_state.json"


class UpdateService:
    """差分更新を統合管理するサービス。"""

    def __init__(
        self,
        documents_api: DocumentsApi,
        metadata_service: MetadataService,
        config: AppConfig,
    ) -> None:
        """初期化する。

        Args:
            documents_api: ドキュメント API ラッパー。
            metadata_service: メタデータサービス。
            config: アプリケーション設定。
        """
        self._docs_api = documents_api
        self._meta_service = metadata_service
        self._config = config
        self._logger = get_logger()
        self._interrupted = False
        self._original_sigint = signal.getsignal(signal.SIGINT)

    def update(
        self,
        force: bool = False,
        meta_overrides: dict[str, str] | None = None,
    ) -> list[UploadResult]:
        """差分更新を実行する。

        Args:
            force: True の場合、全ファイルを強制再アップロードする。
            meta_overrides: CLI --meta オプションの上書き値。

        Returns:
            UploadResult のリスト。
        """
        conn = self._config.connection
        state = self._load_state()

        files = scan_markdown_files(
            conn.target_dir,
            recursive=conn.recursive,
            exclude_patterns=conn.exclude_patterns,
        )

        if not files:
            self._logger.info("更新対象のファイルがありません。")
            return []

        new_files: list[tuple[Path, str]] = []
        changed_files: list[tuple[Path, str, str]] = []
        unchanged_files: list[str] = []

        current_rel_paths: set[str] = set()

        for file_path in files:
            rel_path = self._relative_path(file_path, conn.target_dir)
            current_rel_paths.add(rel_path)
            file_hash = compute_sha256(file_path)

            if rel_path not in state:
                new_files.append((file_path, rel_path))
            elif force or state[rel_path].get("hash") != file_hash:
                doc_id = state[rel_path].get("document_id", "")
                changed_files.append((file_path, rel_path, doc_id))
            else:
                unchanged_files.append(rel_path)

        missing = [rp for rp in state if rp not in current_rel_paths]
        for rp in missing:
            self._logger.warning("ファイルが見つかりません（state に登録あり）: %s", rp)

        self._logger.info(
            "差分分析: 新規 %d 件, 変更 %d 件, 変更なし %d 件, 消失 %d 件",
            len(new_files), len(changed_files), len(unchanged_files), len(missing),
        )

        targets = [(fp, rp, None) for fp, rp in new_files] + \
                  [(fp, rp, did) for fp, rp, did in changed_files]

        if not targets:
            self._logger.info("更新が必要なファイルはありません。")
            return []

        results: list[UploadResult] = []
        self._install_sigint_handler()

        try:
            total = len(targets)
            for i, (file_path, rel_path, doc_id) in enumerate(targets, 1):
                if self._interrupted:
                    self._logger.info("中断シグナルを受信。残りのファイルをスキップします。")
                    break

                if doc_id:
                    result = self._update_single(
                        i, total, file_path, rel_path, doc_id,
                        conn.target_dir, meta_overrides, state,
                    )
                else:
                    result = self._create_single(
                        i, total, file_path, rel_path,
                        conn.target_dir, meta_overrides, state,
                    )
                results.append(result)

                if i < total and not self._interrupted:
                    time.sleep(conn.upload_interval_sec)
        finally:
            self._restore_sigint_handler()
            self._save_state(state)

        self._print_summary(results)
        return results

    def _update_single(
        self,
        index: int,
        total: int,
        file_path: Path,
        rel_path: str,
        document_id: str,
        target_dir: str,
        meta_overrides: dict[str, str] | None,
        state: dict[str, Any],
    ) -> UploadResult:
        """1 ファイルの更新を実行する。

        Args:
            index: 現在のファイル番号。
            total: 全ファイル数。
            file_path: ファイルパス。
            rel_path: 相対パス。
            document_id: 更新対象のドキュメント ID。
            target_dir: ルートディレクトリ。
            meta_overrides: メタデータ上書き値。
            state: 状態辞書。

        Returns:
            更新結果。
        """
        self._logger.info("[%d/%d] 更新中: %s (doc: %s)", index, total, rel_path, document_id[:8])

        try:
            resp = self._docs_api.update_by_file(
                document_id, file_path, self._config.chunking
            )

            doc = resp.get("document", {})
            new_doc_id = doc.get("id", document_id)
            batch = resp.get("batch", "")

            self._logger.info("  → document_id: %s, batch: %s", new_doc_id, batch)

            metadata_applied = False
            if new_doc_id and self._meta_service.field_map:
                try:
                    meta_list = self._meta_service.build_metadata_list(
                        file_path, target_dir, meta_overrides
                    )
                    self._meta_service.apply_metadata(new_doc_id, meta_list)
                    metadata_applied = True
                    self._logger.info("  → メタデータ付与完了")
                except Exception as e:
                    self._logger.warning("  → メタデータ付与失敗: %s", e)

            file_hash = compute_sha256(file_path)
            state[rel_path] = {
                "document_id": new_doc_id,
                "hash": file_hash,
                "uploaded_at": datetime.now().isoformat(),
            }

            return UploadResult(
                relative_path=rel_path,
                document_id=new_doc_id,
                batch=batch,
                metadata_applied=metadata_applied,
                status=UploadStatus.SUCCESS,
            )

        except DifyApiError as e:
            self._logger.error("  → 更新失敗: %s", e)
            return UploadResult(
                relative_path=rel_path,
                status=UploadStatus.FAILED,
                error_message=str(e),
            )
        except Exception as e:
            self._logger.error("  → エラー: %s", e)
            return UploadResult(
                relative_path=rel_path,
                status=UploadStatus.FAILED,
                error_message=str(e),
            )

    def _create_single(
        self,
        index: int,
        total: int,
        file_path: Path,
        rel_path: str,
        target_dir: str,
        meta_overrides: dict[str, str] | None,
        state: dict[str, Any],
    ) -> UploadResult:
        """新規ファイルのアップロードを実行する。

        Args:
            index: 現在のファイル番号。
            total: 全ファイル数。
            file_path: ファイルパス。
            rel_path: 相対パス。
            target_dir: ルートディレクトリ。
            meta_overrides: メタデータ上書き値。
            state: 状態辞書。

        Returns:
            アップロード結果。
        """
        self._logger.info("[%d/%d] 新規アップロード中: %s", index, total, rel_path)

        try:
            resp = self._docs_api.create_by_file(
                file_path, self._config.chunking
            )

            doc = resp.get("document", {})
            document_id = doc.get("id", "")
            batch = resp.get("batch", "")

            self._logger.info("  → document_id: %s, batch: %s", document_id, batch)

            metadata_applied = False
            if document_id and self._meta_service.field_map:
                try:
                    meta_list = self._meta_service.build_metadata_list(
                        file_path, target_dir, meta_overrides
                    )
                    self._meta_service.apply_metadata(document_id, meta_list)
                    metadata_applied = True
                    self._logger.info("  → メタデータ付与完了")
                except Exception as e:
                    self._logger.warning("  → メタデータ付与失敗: %s", e)

            file_hash = compute_sha256(file_path)
            state[rel_path] = {
                "document_id": document_id,
                "hash": file_hash,
                "uploaded_at": datetime.now().isoformat(),
            }

            return UploadResult(
                relative_path=rel_path,
                document_id=document_id,
                batch=batch,
                metadata_applied=metadata_applied,
                status=UploadStatus.SUCCESS,
            )

        except DifyApiError as e:
            self._logger.error("  → アップロード失敗: %s", e)
            return UploadResult(
                relative_path=rel_path,
                status=UploadStatus.FAILED,
                error_message=str(e),
            )
        except Exception as e:
            self._logger.error("  → エラー: %s", e)
            return UploadResult(
                relative_path=rel_path,
                status=UploadStatus.FAILED,
                error_message=str(e),
            )

    def _relative_path(self, file_path: Path, base_dir: str) -> str:
        """ファイルの相対パスを取得する。"""
        try:
            return file_path.relative_to(base_dir).as_posix()
        except ValueError:
            return file_path.name

    def _load_state(self) -> dict[str, Any]:
        """状態ファイルを読み込む。"""
        state_path = Path(STATE_DIR) / STATE_FILE
        if state_path.exists():
            with open(state_path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        """状態ファイルを原子的に保存する。"""
        state_dir = Path(STATE_DIR)
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / STATE_FILE
        tmp_path = state_dir / f"{STATE_FILE}.tmp"

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        os.replace(str(tmp_path), str(state_path))
        self._logger.debug("状態ファイルを保存: %s", state_path)

    def _install_sigint_handler(self) -> None:
        """SIGINT ハンドラを設定する。"""

        def _handler(signum: int, frame: Any) -> None:
            self._logger.info("\n中断シグナル (Ctrl+C) を受信。安全に停止します...")
            self._interrupted = True

        self._original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _handler)

    def _restore_sigint_handler(self) -> None:
        """SIGINT ハンドラを元に戻す。"""
        signal.signal(signal.SIGINT, self._original_sigint)

    def _print_summary(self, results: list[UploadResult]) -> None:
        """結果サマリーをテーブル形式で表示する。"""
        if not results:
            return

        sep = "─" * 78
        self._logger.info("")
        self._logger.info(sep)
        self._logger.info(
            "%4s  %-35s  %-16s  %s  %s",
            "#", "ファイル", "document_id", "メタ", "結果",
        )
        self._logger.info(sep)

        for i, r in enumerate(results, 1):
            doc_id = (r.document_id[:13] + "...") if len(r.document_id) > 16 else (r.document_id or "-")
            meta_mark = "✓" if r.metadata_applied else "-"
            if r.status == UploadStatus.SUCCESS:
                status_text = r.status.value
            else:
                status_text = f"{r.status.value}: {r.error_message[:30]}"

            path_display = r.relative_path
            if len(path_display) > 35:
                path_display = "..." + path_display[-32:]

            self._logger.info(
                "%4d  %-35s  %-16s  %s    %s",
                i, path_display, doc_id, meta_mark, status_text,
            )

        self._logger.info(sep)

        success = sum(1 for r in results if r.status == UploadStatus.SUCCESS)
        failed = sum(1 for r in results if r.status == UploadStatus.FAILED)
        total = len(results)

        parts = [f"成功: {success}/{total}"]
        if failed:
            parts.append(f"失敗: {failed}/{total}")
        self._logger.info("  ".join(parts))
