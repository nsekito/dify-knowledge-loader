"""CLI エントリーポイント。

argparse によるサブコマンドを提供し、各サービスを呼び出す。
使用例: python -m src.main upload
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from typing import Sequence

from src.api.client import DifyClient
from src.api.documents import DocumentsApi
from src.api.metadata import MetadataApi
from src.config import AppConfig, load_config
from src.services.metadata_service import MetadataService
from src.services.update_service import UpdateService
from src.services.upload_service import UploadService
from src.utils.logger import get_logger, setup_logger

WATCH_INTERVAL_SEC = 5


def main(argv: Sequence[str] | None = None) -> int:
    """CLI のメインエントリーポイント。

    Args:
        argv: コマンドライン引数（テスト用に外部から渡せる）。

    Returns:
        終了コード（0: 成功, 1: エラー）。
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    logger = setup_logger()

    try:
        config = load_config(args.config_dir)
    except (FileNotFoundError, ValueError) as e:
        logger.error("設定エラー: %s", e)
        return 1

    try:
        return args.func(args, config)
    except ConnectionError as e:
        logger.error("接続エラー: %s", e)
        return 1
    except KeyboardInterrupt:
        logger.info("処理を中断しました。")
        return 1
    except Exception as e:
        logger.error("予期しないエラー: %s", e, exc_info=True)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    """argparse パーサーを構築する。

    Returns:
        設定済みの ArgumentParser。
    """
    parser = argparse.ArgumentParser(
        prog="dify-knowledge-loader",
        description="Dify ナレッジベースへの Markdown 一括登録ツール",
    )
    parser.add_argument(
        "--config-dir",
        default="./config",
        help="設定ディレクトリのパス（デフォルト: ./config）",
    )

    subparsers = parser.add_subparsers(title="コマンド", dest="command")

    # upload コマンド
    upload_parser = subparsers.add_parser(
        "upload", help="Markdown ファイルをナレッジベースにアップロード"
    )
    upload_parser.add_argument(
        "--dir", dest="target_dir", default=None,
        help="対象ディレクトリ（connection.yaml の target_dir を一時的に上書き）",
    )
    upload_parser.add_argument(
        "--file", dest="single_file", default=None,
        help="単一ファイルをアップロード",
    )
    upload_parser.add_argument(
        "--meta", action="append", default=[],
        metavar="KEY=VALUE",
        help="メタデータ値を上書き（複数指定可）",
    )
    upload_parser.add_argument(
        "--dry-run", action="store_true",
        help="API を叩かず処理予定を表示",
    )
    upload_parser.set_defaults(func=_cmd_upload)

    # update コマンド
    update_parser = subparsers.add_parser(
        "update", help="前回から変更があったファイルのみ更新"
    )
    update_parser.add_argument(
        "--force", action="store_true",
        help="強制的に全ファイルを再アップロード",
    )
    update_parser.add_argument(
        "--meta", action="append", default=[],
        metavar="KEY=VALUE",
        help="メタデータ値を上書き（複数指定可）",
    )
    update_parser.set_defaults(func=_cmd_update)

    # status コマンド
    status_parser = subparsers.add_parser(
        "status", help="ナレッジベースのドキュメント一覧と状態を表示"
    )
    status_parser.add_argument(
        "--watch", action="store_true",
        help="インデクシング進捗をリアルタイムポーリング",
    )
    status_parser.set_defaults(func=_cmd_status)

    # metadata コマンド
    meta_parser = subparsers.add_parser(
        "metadata", help="メタデータフィールドの管理"
    )
    meta_sub = meta_parser.add_subparsers(title="サブコマンド", dest="meta_command")

    meta_list_parser = meta_sub.add_parser(
        "list", help="メタデータフィールド一覧を表示"
    )
    meta_list_parser.set_defaults(func=_cmd_metadata_list)

    meta_sync_parser = meta_sub.add_parser(
        "sync", help="metadata.yaml のフィールド定義をナレッジベースに同期"
    )
    meta_sync_parser.set_defaults(func=_cmd_metadata_sync)

    return parser


def _parse_meta_args(meta_args: list[str]) -> dict[str, str]:
    """--meta KEY=VALUE 引数をパースする。

    Args:
        meta_args: KEY=VALUE 形式の文字列リスト。

    Returns:
        パース済みの辞書。
    """
    result: dict[str, str] = {}
    for item in meta_args:
        if "=" not in item:
            get_logger().warning("無効な --meta 引数（KEY=VALUE 形式にしてください）: %s", item)
            continue
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _create_services(config: AppConfig) -> tuple[DifyClient, DocumentsApi, MetadataApi, MetadataService]:
    """共通サービスを初期化する。

    Args:
        config: アプリケーション設定。

    Returns:
        (DifyClient, DocumentsApi, MetadataApi, MetadataService) のタプル。
    """
    client = DifyClient(config.connection.base_url, config.connection.api_key)
    docs_api = DocumentsApi(client, config.connection.dataset_id)
    meta_api = MetadataApi(client, config.connection.dataset_id)
    meta_service = MetadataService(meta_api, config.metadata)
    return client, docs_api, meta_api, meta_service


def _cmd_upload(args: argparse.Namespace, config: AppConfig) -> int:
    """upload コマンドを実行する。"""
    logger = get_logger()

    client, docs_api, meta_api, meta_service = _create_services(config)
    client.check_connection(config.connection.dataset_id)

    if not args.dry_run:
        meta_service.sync_fields()

    upload_service = UploadService(docs_api, meta_service, config)
    meta_overrides = _parse_meta_args(args.meta)

    results = upload_service.upload(
        target_dir=args.target_dir,
        single_file=args.single_file,
        meta_overrides=meta_overrides if meta_overrides else None,
        dry_run=args.dry_run,
    )

    failed = sum(1 for r in results if r.status.name == "FAILED")
    return 1 if failed > 0 else 0


def _cmd_update(args: argparse.Namespace, config: AppConfig) -> int:
    """update コマンドを実行する。"""
    logger = get_logger()

    client, docs_api, meta_api, meta_service = _create_services(config)
    client.check_connection(config.connection.dataset_id)
    meta_service.sync_fields()

    update_service = UpdateService(docs_api, meta_service, config)
    meta_overrides = _parse_meta_args(args.meta)

    results = update_service.update(
        force=args.force,
        meta_overrides=meta_overrides if meta_overrides else None,
    )

    failed = sum(1 for r in results if r.status.name == "FAILED")
    return 1 if failed > 0 else 0


def _cmd_status(args: argparse.Namespace, config: AppConfig) -> int:
    """status コマンドを実行する。"""
    logger = get_logger()

    client, docs_api, _, _ = _create_services(config)
    client.check_connection(config.connection.dataset_id)

    if args.watch:
        return _watch_status(docs_api)

    docs = docs_api.list_all_documents()

    if not docs:
        logger.info("ナレッジベースにドキュメントがありません。")
        return 0

    sep = "─" * 80
    logger.info("")
    logger.info(sep)
    logger.info(
        "%4s  %-30s  %-15s  %-8s  %s",
        "#", "ドキュメント名", "ステータス", "有効", "作成日時",
    )
    logger.info(sep)

    for i, doc in enumerate(docs, 1):
        created = ""
        if doc.created_at:
            created = datetime.fromtimestamp(doc.created_at).strftime("%Y-%m-%d %H:%M")

        name_display = doc.name
        if len(name_display) > 30:
            name_display = name_display[:27] + "..."

        enabled_mark = "✓" if doc.enabled else "✗"

        logger.info(
            "%4d  %-30s  %-15s  %-8s  %s",
            i, name_display, doc.indexing_status, enabled_mark, created,
        )

    logger.info(sep)
    logger.info("合計: %d 件", len(docs))
    return 0


def _watch_status(docs_api: DocumentsApi) -> int:
    """インデクシング進捗をポーリングする。

    Args:
        docs_api: ドキュメント API。

    Returns:
        終了コード。
    """
    logger = get_logger()
    logger.info("インデクシング状態をポーリング中（%d 秒間隔）... Ctrl+C で停止", WATCH_INTERVAL_SEC)

    try:
        while True:
            docs = docs_api.list_all_documents()

            in_progress = [
                d for d in docs
                if d.indexing_status not in ("completed", "error", "")
            ]

            completed = sum(1 for d in docs if d.indexing_status == "completed")
            errors = sum(1 for d in docs if d.indexing_status == "error")

            logger.info(
                "[%s] 全体: %d 件 | 完了: %d | 処理中: %d | エラー: %d",
                datetime.now().strftime("%H:%M:%S"),
                len(docs), completed, len(in_progress), errors,
            )

            for d in in_progress:
                logger.info(
                    "  %-30s  %s", d.name[:30], d.indexing_status,
                )

            if not in_progress:
                logger.info("全ドキュメントの処理が完了しました。")
                return 0

            time.sleep(WATCH_INTERVAL_SEC)

    except KeyboardInterrupt:
        logger.info("ポーリングを停止しました。")
        return 0


def _cmd_metadata_list(args: argparse.Namespace, config: AppConfig) -> int:
    """metadata list コマンドを実行する。"""
    logger = get_logger()

    client, _, meta_api, meta_service = _create_services(config)
    client.check_connection(config.connection.dataset_id)

    fields = meta_service.list_fields()

    if not fields:
        logger.info("メタデータフィールドが定義されていません。")
        return 0

    sep = "─" * 60
    logger.info("")
    logger.info(sep)
    logger.info("%-20s  %-10s  %-10s  %s", "フィールド名", "型", "使用数", "ID")
    logger.info(sep)

    for f in fields:
        logger.info("%-20s  %-10s  %-10d  %s", f.name, f.type, f.use_count, f.id)

    logger.info(sep)
    logger.info("合計: %d フィールド", len(fields))
    return 0


def _cmd_metadata_sync(args: argparse.Namespace, config: AppConfig) -> int:
    """metadata sync コマンドを実行する。"""
    logger = get_logger()

    client, _, meta_api, meta_service = _create_services(config)
    client.check_connection(config.connection.dataset_id)

    field_map = meta_service.sync_fields()
    logger.info("同期されたフィールド:")
    for name, field_id in field_map.items():
        logger.info("  %s → %s", name, field_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
