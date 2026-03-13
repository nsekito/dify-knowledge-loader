# dify-knowledge-loader

閉塞ネットワーク環境の Windows 端末から、Dify サーバのナレッジベースに大量の Markdown ファイルを一括登録する Python CLI ツールです。メタデータの自動付与、差分更新、インデクシング状態監視に対応しています。

---

## 前提条件

| 項目 | 要件 |
|------|------|
| OS | Windows 10 / 11 |
| Python | 3.10 以上 |
| 外部ライブラリ | requests, PyYAML |
| Dify バージョン | **v1.13.0**（Self-Hosted / Docker） |
| ネットワーク | Dify サーバに HTTP でアクセス可能（インターネット接続不要） |

---

## セットアップ手順

### 1. リポジトリの配置

```
git clone https://github.com/nsekito/dify-knowledge-loader.git
cd dify-knowledge-loader
```

またはアーカイブを展開して配置します。

### 2. オフライン環境でのライブラリインストール

閉塞環境では `.whl` ファイルを持ち込んでインストールします。

**インターネット接続のある端末で事前準備:**

```bash
pip download requests PyYAML -d ./wheels
```

**閉塞環境の端末で:**

```bash
pip install --no-index --find-links=./wheels requests PyYAML
```

または個別にインストール:

```bash
pip install requests-2.x.x-py3-none-any.whl
pip install PyYAML-6.x.x-cpXX-cpXX-win_amd64.whl
```

### 3. 設定ファイルの作成

```
cd config
copy connection.yaml.example connection.yaml
copy chunking.yaml.example chunking.yaml
copy metadata.yaml.example metadata.yaml
```

`connection.yaml` を編集し、以下を設定してください:

- `base_url`: Dify サーバの URL
- `api_key`: ナレッジベースの API キー
- `dataset_id`: 対象ナレッジベースの ID
- `target_dir`: Markdown ファイルの格納ディレクトリ

API キーとナレッジベース ID の確認方法:
- API キー: Dify 管理画面 → ナレッジ → API アクセス → API キー
- ナレッジベース ID: ナレッジを選択したときの URL の `datasets/` 以降の UUID

---

## 使い方

### 基本: upload（一括アップロード）

```bash
# config/connection.yaml の target_dir に格納された .md ファイルを一括アップロード
python -m src.main upload

# ディレクトリを指定してアップロード（connection.yaml の target_dir を一時的に上書き）
python -m src.main upload --dir "C:\docs\manuals"

# 単一ファイルをアップロード
python -m src.main upload --file "C:\docs\設計書.md"

# メタデータ値を CLI から上書き
python -m src.main upload --meta section="設計書" --meta author="田中"
```

### 差分更新: update

```bash
# 前回から変更があったファイルのみ更新
python -m src.main update

# 強制的に全ファイルを再アップロード
python -m src.main update --force
```

### 状態確認: status

```bash
# ナレッジベースのドキュメント一覧とインデクシング状態を表示
python -m src.main status

# インデクシング中のドキュメントの進捗をリアルタイムポーリング（5秒間隔）
python -m src.main status --watch
```

### メタデータ管理: metadata

```bash
# ナレッジベースのメタデータフィールド一覧を表示
python -m src.main metadata list

# config/metadata.yaml のフィールド定義をナレッジベースに同期
python -m src.main metadata sync
```

### ドライラン

```bash
# API を叩かず処理予定を表示
python -m src.main upload --dry-run
```

### Windows タスクスケジューラでの定期実行

1. タスクスケジューラを開く（`taskschd.msc`）
2. 「基本タスクの作成」を選択
3. トリガー: 毎日 / 毎時間など任意に設定
4. 操作:
   - プログラム: `python`
   - 引数: `-m src.main update`
   - 開始: `C:\path\to\dify-knowledge-loader`（リポジトリのパス）

---

## 設定ファイルリファレンス

### connection.yaml — Dify 接続情報

| 項目 | 型 | 必須 | デフォルト | 説明 |
|------|----|:----:|-----------|------|
| `base_url` | string | ✅ | - | Dify サーバの URL（末尾スラッシュなし） |
| `api_key` | string | ✅ | - | ナレッジベースの API キー |
| `dataset_id` | string | ✅ | - | 対象ナレッジベース ID |
| `target_dir` | string | ✅ | - | Markdown ファイルの格納ディレクトリ |
| `recursive` | bool | | `true` | サブディレクトリを再帰的に探索するか |
| `exclude_patterns` | list | | `[]` | 除外パターン（glob 形式） |
| `upload_interval_sec` | float | | `1.0` | API リクエスト間の待機秒数 |

### chunking.yaml — チャンク分割設定

| 項目 | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `indexing_technique` | string | `"high_quality"` | `"high_quality"` または `"economy"` |
| `mode` | string | `"automatic"` | `"automatic"` または `"custom"` |
| `custom.separator` | string | `"\\n"` | チャンク分割セパレータ |
| `custom.max_tokens` | int | `500` | 1チャンクの最大トークン数 |
| `custom.pre_processing.remove_extra_spaces` | bool | `true` | 連続する空白を圧縮 |
| `custom.pre_processing.remove_urls_emails` | bool | `false` | URL・メールアドレスを除去 |

> `custom` セクションは `mode: "custom"` のときのみ有効です。
> 初回は `mode: "automatic"` から始めることを推奨します。

### metadata.yaml — メタデータ設定

| 項目 | 型 | 説明 |
|------|----|------|
| `fields` | list | ナレッジベースに作成するメタデータフィールドの定義 |
| `fields[].name` | string | フィールド名 |
| `fields[].type` | string | フィールド型（`"string"` / `"number"` / `"time"`） |
| `values` | dict | 各ファイルに付与するメタデータの値 |

---

## メタデータについて

### 自動値（auto）

| 値 | 動作 | 例 |
|----|------|----|
| `auto:filename` | ファイル名を自動設定 | `setup.md` |
| `auto:relative_path` | target_dir からの相対パスを自動設定 | `manual/setup.md` |

### 固定値

`values` に文字列・数値を指定すると、全ファイルに共通で付与されます。

### CLI での上書き

`--meta` オプションで metadata.yaml の値を上書きできます:

```bash
python -m src.main upload --meta section="設計書" --meta author="田中"
```

---

## ディレクトリ構成の例

### Markdown ファイルの配置例

```
C:\docs\knowledge\
├── manual\
│   ├── setup.md
│   └── install.md
├── guide\
│   ├── overview.md
│   └── faq.md
└── reference\
    └── api.md
```

### metadata.yaml の設定

```yaml
fields:
  - name: "original_filename"
    type: "string"
  - name: "file_path"
    type: "string"
  - name: "section"
    type: "string"

values:
  original_filename: "auto:filename"
  file_path: "auto:relative_path"
  section: ""
```

### 付与されるメタデータ

| ファイル | original_filename | file_path | section |
|----------|-------------------|-----------|---------|
| manual/setup.md | setup.md | manual/setup.md | （CLI で指定した値） |
| manual/install.md | install.md | manual/install.md | （CLI で指定した値） |
| guide/overview.md | overview.md | guide/overview.md | （CLI で指定した値） |

`section` は `--meta section="マニュアル"` のように CLI で上書きできます。

---

## トラブルシューティング

### 接続エラー: Dify サーバに接続できません

- `connection.yaml` の `base_url` が正しいか確認してください
- Dify サーバが起動しているか確認してください
- ファイアウォールでポートがブロックされていないか確認してください

### 認証エラー: 401 Unauthorized

- `connection.yaml` の `api_key` が正しいか確認してください
- API キーが有効であることを Dify 管理画面で確認してください

### ファイルサイズ超過: 413 file_too_large

- Dify にはファイルサイズの上限があります（デフォルト 15MB）
- 大きなファイルは分割してからアップロードしてください

### インデクシングエラー: document_indexing

- ドキュメントがインデクシング中です。完了を待ってから再実行してください
- `python -m src.main status --watch` で進捗を確認できます

### メタデータ付与エラー: invalid_metadata

- `metadata.yaml` の `fields` に定義されていないフィールドを `values` で参照していないか確認してください
- `python -m src.main metadata sync` でフィールドを同期してください

### ログの確認

詳細ログは `logs/` ディレクトリに出力されます:

```
logs/20260314_100000.log
```

DEBUG レベルの情報が含まれるため、問題の特定に役立ちます。

---

## 制限事項・既知の問題

- **ファイルアップロードとメタデータ付与は2段階処理**: Dify API ではファイルアップロード時にメタデータを同時付与できないため、「アップロード → メタデータ後付け」の2段階で処理しています（[GitHub Issue #21519](https://github.com/langgenius/dify/issues/21519)）
- **バッチアップロード非対応**: Dify API にはバッチアップロード API が存在しないため、1ファイルずつ順次処理します
- **チャンク設定**: `mode: "custom"` は Dify v1.13.0 で動作確認済みですが、一部の古いバージョンでは `max_tokens` が正しく反映されない場合があります。不安な場合は `mode: "automatic"` を使用してください
- **ファイル削除の自動化なし**: `update` コマンドでファイルが消失した場合、ログに警告を出しますが Dify 上のドキュメントは自動削除しません
- **外部ライブラリ**: `requests` と `PyYAML` のみ使用。インターネット接続は不要です
