# NFC Batch Writer

CSVやURLを使って、NFCタグへNDEFデータを連続書き込みするツールです。  
ブラウザUI・GUI・CLIの3モードに対応しています。

## 機能

- **CSV連続書き込み** — CSVの各行を順番にNFCタグへ書き込み、成功したら自動で次の行へ進む
- **単一URL繰り返し書き込み** — 同じURLを何枚ものタグに連続で書き込む
- **同一タグ検知** — 書き込み済みのタグを外さずにかざし続けても重複書き込みしない
- **1つ戻す** — 書き込みミス時にカーソルを1行戻せる
- **モックモード** — NFCリーダーがなくても動作確認できる
- **成功/失敗時のビープ音**（macOS対応）

## 必要なもの

- Python 3.9 以上
- （実機書き込みの場合）PC/SC対応のUSB NFCリーダー/ライター
  - 動作確認済み: [SpringCard PUCK Base](https://www.springcard.com/en/products/puck-base)
  - ACR122U系なども `src/nfc_backends/` を調整すれば対応可能

> **macOSの内蔵NFCでは任意のタグへの書き込みはできません。** USB接続のリーダー/ライターが必要です。

## セットアップ

```bash
# リポジトリをクローン
git clone https://github.com/<your-username>/nfc-batch-writer.git
cd nfc-batch-writer

# Python仮想環境を作成・有効化
python3 -m venv .venv
source .venv/bin/activate

# 依存パッケージをインストール
pip install -r requirements.txt
```

### pyscardのインストールでエラーが出る場合（macOS）

```bash
# Xcode Command Line Tools
xcode-select --install

# swigが必要な場合
brew install swig

# 再インストール
pip install pyscard
```

## 使い方

### ブラウザUI（おすすめ）

```bash
source .venv/bin/activate
python3 -m src.web_main
```

ブラウザで http://127.0.0.1:8787 を開きます。

1. **モード選択** — 「単一URL」か「CSV」を選ぶ
2. **CSVモードの場合** — CSVファイルをアップロード
3. **リーダー選択** — Mock（実機なし）またはPC/SC（実機）を選ぶ
4. **開始ボタン** — タグをかざすと書き込み開始

### CLI

```bash
# モックモード（実機なし・動作確認用）
python3 -m src.app --cli --mock --csv sample.csv

# 実機モード（PC/SCリーダー使用）
python3 -m src.app --cli --pcsc --csv sample.csv

# リーダー名を指定（デフォルト: SpringCard）
python3 -m src.app --cli --pcsc --reader-contains "ACR122" --csv sample.csv
```

### GUI（tkinter）

```bash
python3 -m src.app --csv sample.csv
```

## CSVフォーマット

### URL書き込み（推奨）

```csv
url
https://example.com/product/001
https://example.com/product/002
https://example.com/product/003
```

### payload列でもOK（URLとして扱われます）

```csv
payload
https://example.com/a
https://example.com/b
```

### type指定（URIとテキストを混在させる場合）

```csv
type,payload
uri,https://example.com/a
text,こんにちは
```

- `type`: `uri` または `text`
- `payload`: 書き込む内容

## プロジェクト構成

```
├── src/
│   ├── app.py              # エントリーポイント（GUI/CLI振り分け）
│   ├── cli.py              # CLIモード
│   ├── gui.py              # tkinter GUIモード
│   ├── web_main.py         # ブラウザUI起動（uvicorn）
│   ├── web_app.py          # ブラウザUI（FastAPI + SSE）
│   ├── csv_queue.py        # CSV読み込み
│   ├── ndef.py             # NDEFレコード生成
│   ├── sound.py            # ビープ音
│   └── nfc_backends/
│       ├── base.py         # バックエンド共通インターフェース
│       ├── mock.py         # モック（実機不要）
│       └── springcore_pcsc.py  # SpringCard PC/SCリーダー用
├── sample.csv              # サンプルCSV
├── requirements.txt
└── README.md
```

## 別のNFCリーダーを使う場合

`src/nfc_backends/base.py` の `NfcWriter` インターフェースを実装した新しいバックエンドを作成してください。`write_uri()` と `write_text()` を実装すればOKです。

## ライセンス

MIT
