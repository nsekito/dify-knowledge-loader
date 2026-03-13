"""Dify API 共通クライアントモジュール。

認証ヘッダの付与、リトライ（指数バックオフ）、エラーハンドリングを提供する。
"""

from __future__ import annotations

import time
from typing import Any

import requests

from src.utils.logger import get_logger

MAX_RETRIES = 3
BACKOFF_BASE = 2  # 2, 4, 8 秒


class DifyApiError(Exception):
    """Dify API から返却されたエラーを表す例外。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"[{status_code}] {code}: {message}")


class DifyClient:
    """Dify API への HTTP リクエストを管理する共通クライアント。

    認証ヘッダの付与、ネットワークエラー時の自動リトライ、
    Dify 固有のエラーレスポンス解析を一元的に処理する。
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        """クライアントを初期化する。

        Args:
            base_url: Dify サーバの URL（末尾スラッシュなし）。
            api_key: ナレッジベース API キー。
        """
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
        })
        self._logger = get_logger()

    def check_connection(self, dataset_id: str) -> bool:
        """Dify サーバへの疎通を確認する。

        GET /v1/datasets?page=1&limit=1 を送信し、応答を確認する。

        Args:
            dataset_id: データセット ID（ログ用）。

        Returns:
            疎通成功なら True。

        Raises:
            ConnectionError: サーバに接続できない場合。
        """
        self._logger.info("Dify サーバへの接続を確認中: %s", self.base_url)
        try:
            resp = self.get("/v1/datasets", params={"page": 1, "limit": 1})
            self._logger.info("接続確認成功（ナレッジベース数: %d）", resp.get("total", 0))
            return True
        except Exception as e:
            raise ConnectionError(
                f"Dify サーバに接続できません: {self.base_url}\n  → {e}"
            ) from e

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """GET リクエストを送信する。

        Args:
            path: API パス（例: /v1/datasets）。
            params: クエリパラメータ。

        Returns:
            JSON レスポンスの辞書。
        """
        return self._request("GET", path, params=params)

    def post_json(self, path: str, json_data: dict[str, Any] | None = None) -> dict:
        """JSON ボディの POST リクエストを送信する。

        Args:
            path: API パス。
            json_data: リクエストボディ。

        Returns:
            JSON レスポンスの辞書。
        """
        return self._request("POST", path, json=json_data)

    def post_multipart(
        self,
        path: str,
        files: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> dict:
        """multipart/form-data の POST リクエストを送信する。

        Args:
            path: API パス。
            files: アップロードファイル。
            data: フォームデータ。

        Returns:
            JSON レスポンスの辞書。
        """
        return self._request("POST", path, files=files, data=data)

    def patch(self, path: str, json_data: dict[str, Any] | None = None) -> dict:
        """PATCH リクエストを送信する。

        Args:
            path: API パス。
            json_data: リクエストボディ。

        Returns:
            JSON レスポンスの辞書。
        """
        return self._request("PATCH", path, json=json_data)

    def delete(self, path: str) -> dict:
        """DELETE リクエストを送信する。

        Args:
            path: API パス。

        Returns:
            JSON レスポンスの辞書。
        """
        return self._request("DELETE", path)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        """HTTP リクエストをリトライ付きで実行する。

        ネットワークエラー時は指数バックオフで最大 MAX_RETRIES 回リトライする。
        Dify API エラーレスポンスは DifyApiError として送出する。

        Args:
            method: HTTP メソッド。
            path: API パス。
            **kwargs: requests に渡す追加引数。

        Returns:
            JSON レスポンスの辞書。

        Raises:
            DifyApiError: API エラーレスポンスの場合。
            ConnectionError: リトライ上限を超えた場合。
        """
        url = f"{self.base_url}{path}"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._logger.debug(
                    "%s %s (試行 %d/%d)", method, path, attempt, MAX_RETRIES
                )
                resp = self.session.request(method, url, timeout=60, **kwargs)
                return self._handle_response(resp)

            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == MAX_RETRIES:
                    raise ConnectionError(
                        f"ネットワークエラー（{MAX_RETRIES} 回リトライ後も失敗）: {e}"
                    ) from e

                wait = BACKOFF_BASE ** attempt
                self._logger.warning(
                    "ネットワークエラー（試行 %d/%d）。%d 秒後にリトライ: %s",
                    attempt,
                    MAX_RETRIES,
                    wait,
                    e,
                )
                time.sleep(wait)

        raise ConnectionError("リトライ上限に達しました")

    def _handle_response(self, resp: requests.Response) -> dict:
        """レスポンスを解析し、エラーがあれば例外を送出する。

        Args:
            resp: requests のレスポンスオブジェクト。

        Returns:
            JSON レスポンスの辞書。

        Raises:
            DifyApiError: API がエラーを返した場合。
        """
        try:
            body = resp.json()
        except ValueError:
            if resp.status_code >= 400:
                raise DifyApiError(resp.status_code, "unknown", resp.text)
            return {}

        if resp.status_code >= 400:
            code = body.get("code", "unknown")
            message = body.get("message", resp.text)
            raise DifyApiError(resp.status_code, code, message)

        return body
