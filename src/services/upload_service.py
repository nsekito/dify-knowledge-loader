"""アップロードのビジネスロジック。

ファイルスキャン、順次アップロード、メタデータ付与、
状態管理、結果サマリー表示を統合的に処理する。
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


class UploadService:
    """ファイルアップロードを統合管理するサービス。"""

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

    def upload(
        self,
        target_dir: str | None = None,
        single_file: str | None = None,
        meta_overrides: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> list[UploadResult]:
        """ファイルをアップロードする。

        Args:
            target_dir: 対象ディレクトリ（None の場合は設定ファイルの値を使用）。
            single_file: 単一ファイルパス（指定時はそのファイルのみ処理）。
            meta_overrides: CLI --meta オプションの上書き値。
            dry_run: True の場合 API を叩かず処理予定を表示。

        Returns:
            UploadResult のリスト。
        """
        conn = self._config.connection
        effective_dir = target_dir or conn.target_dir

        if single_file:
            files = [Path(single_file)]
            if not files[0].exists():
                raise FileNotFoundError(f"ファイルが見つかりません: {single_file}")
        else:
            files = scan_markdown_files(
                effective_dir,
                recursive=conn.recursive,
                exclude_patterns=conn.exclude_patterns,
            )

        if not files:
            self._logger.info("アップロード対象のファイルがありません。")
            return []

        if dry_run:
            return self._dry_run(files, effective_dir)

        state = self._load_state()
        results: list[UploadResult] = []

        self._install_sigint_handler()

        try:
            total = len(files)
            for i, file_path in enumerate(files, 1):
                if self._interrupted:
                    self._logger.info("中断シグナルを受信。残りのファイルをスキップします。")
                    break

                rel_path = self._relative_path(file_path, effective_dir)
                result = self._upload_single(
                    i, total, file_path, rel_path, effective_dir, meta_overrides, state
                )
                results.append(result)

                if i < total and not self._interrupted:
                    time.sleep(conn.upload_interval_sec)
        finally:
            self._restore_sigint_handler()
            self._save_state(state)

        self._print_summary(results)
        return results

    def _dry_run(self, files: list[Path], effective_dir: str) -> list[UploadResult]:
        """ドライランモードで処理予定を表示する。

        Args:
            files: 対象ファイルリスト。
            effective_dir: ルートディレクトリ。

        Returns:
            SKIPPED ステータスの UploadResult リスト。
        """
        self._logger.info("=== ドライラン: API リクエストは送信されません ===")
        results: list[UploadResult] = []

        for i, file_path in enumerate(files, 1):
            rel = self._relative_path(file_path, effective_dir)
            self._logger.info("[%d/%d] アップロード予定: %s", i, len(files), rel)
            results.append(UploadResult(
                relative_path=rel,
                status=UploadStatus.SKIPPED,
                error_message="ドライラン",
            ))

        self._logger.info("=== ドライラン完了: %d 件が処理対象 ===", len(files))
        return results

    def _upload_single(
        self,
        index: int,
        total: int,
        file_path: Path,
        rel_path: str,
        effective_dir: str,
        meta_overrides: dict[str, str] | None,
        state: dict[str, Any],
    ) -> UploadResult:
        """1 ファイルのアップロードを実行する。

        Args:
            index: 現在のファイル番号。
            total: 全ファイル数。
            file_path: ファイルパス。
            rel_path: 相対パス。
            effective_dir: ルートディレクトリ。
            meta_overrides: メタデータ上書き値。
            state: 状態辞書。

        Returns:
            アップロード結果。
        """
        self._logger.info("[%d/%d] アップロード中: %s", index, total, rel_path)

        try:
            resp = self._docs_api.create_by_file(
                file_path, self._config.chunking
            )

            doc = resp.get("document", {})
            document_id = doc.get("id", "")
            batch = resp.get("batch", "")

            self._logger.info(
                "  → document_id: %s, batch: %s", document_id, batch
            )

            metadata_applied = False
            if document_id and self._meta_service.field_map:
                try:
                    meta_list = self._meta_service.build_metadata_list(
                        file_path, effective_dir, meta_overrides
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
        """ファイルの相対パスを取得する。

        Args:
            file_path: ファイルの絶対パス。
            base_dir: ベースディレクトリ。

        Returns:
            POSIX 形式の相対パス。
        """
        try:
            return file_path.relative_to(base_dir).as_posix()
        except ValueError:
            return file_path.name

    def _load_state(self) -> dict[str, Any]:
        """状態ファイルを読み込む。

        Returns:
            状態辞書。ファイルが存在しない場合は空辞書。
        """
        state_path = Path(STATE_DIR) / STATE_FILE
        if state_path.exists():
            with open(state_path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        """状態ファイルを原子的に保存する。

        一時ファイルに書き込んだ後にリネームすることで、
        書き込み中のクラッシュによるデータ破損を防ぐ。

        Args:
            state: 保存する状態辞書。
        """
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
        """結果サマリーをテーブル形式で表示する。

        Args:
            results: アップロード結果のリスト。
        """
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
            elif r.status == UploadStatus.SKIPPED:
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
        skipped = sum(1 for r in results if r.status == UploadStatus.SKIPPED)
        total = len(results)

        parts = [f"成功: {success}/{total}"]
        if failed:
            parts.append(f"失敗: {failed}/{total}")
        if skipped:
            parts.append(f"スキップ: {skipped}/{total}")

        self._logger.info("  ".join(parts))
