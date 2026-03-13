# 設定ファイルガイド

## セットアップ手順

1. `.example` ファイルをコピーして設定ファイルを作成します

   ```
   cd config
   copy connection.yaml.example connection.yaml
   copy chunking.yaml.example chunking.yaml
   copy metadata.yaml.example metadata.yaml
   ```

2. 各ファイルを編集します（詳細は各ファイル内のコメントを参照）

## ファイル一覧

| ファイル名          | 内容                       | 必ず編集が必要？ |
|---------------------|---------------------------|:---:|
| connection.yaml     | サーバ URL、API キー、対象ディレクトリ | ✅ |
| chunking.yaml       | チャンク分割ルール          | （デフォルトで可） |
| metadata.yaml       | メタデータのフィールド定義と値 | 必要に応じて |

## 注意事項

- connection.yaml には API キーが含まれるため、Git にコミットしないでください
- .gitignore で connection.yaml は除外されています
