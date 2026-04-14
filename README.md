# NFC Batch Writer

NFCタグにURLやテキストを一括で書き込むツールです。  
スマホでタグをかざすだけで指定のWebページが開くようになります。

## できること

- **CSV一括書き込み** — CSVファイルに書いたURLを、1枚ずつ順番にNFCタグへ書き込み
- **同じURLを大量に書き込み** — 1つのURLを何十枚ものタグに連続で書き込み
- **書き込みミス防止** — 同じタグへの重複書き込みを自動で検知。書き込み後に読み戻し検証あり
- **1つ戻す** — 間違えたら1行前に戻せる
- **リーダーなしでお試し** — モックモードでリーダーがなくても動作確認OK

## 用意するもの

| # | 必要なもの | 備考 |
|---|-----------|------|
| 1 | **パソコン** | Mac / Windows どちらでもOK |
| 2 | **Python 3.9 以上** | [python.org](https://www.python.org/downloads/) からダウンロード |
| 3 | **USB NFCリーダー/ライター** | 下記のおすすめ参照 |
| 4 | **書き込み用NFCタグ** | NTAG213 / NTAG215 / NTAG216 など（NFC Forum Type 2 Tag） |

### おすすめNFCリーダー

- **[ACR122U](https://www.acs.com.hk/en/products/3/acr122u-nfc-contactless-smart-card-reader/)** — 動作確認済み。Amazonなどで3,000〜5,000円程度。定番で情報も多い
- [SpringCard PUCK Base](https://www.springcard.com/en/products/puck-base) — 動作確認済み

> **macOSの内蔵NFCではタグへの書き込みはできません。** 必ずUSB接続のリーダーが必要です。

---

## 導入手順（はじめての方向け）

### Step 1: Pythonをインストール

既にインストール済みの方はスキップしてください。

1. [python.org](https://www.python.org/downloads/) にアクセス
2. 「Download Python 3.x.x」ボタンをクリックしてダウンロード
3. ダウンロードしたファイルを開いてインストール
   - **Windows の場合:** インストール画面で **「Add Python to PATH」にチェックを入れてから** インストール

### Step 2: NFCリーダー（ACR122U）のセットアップ

1. [ACR122U 製品ページ](https://www.acs.com.hk/en/products/3/acr122u-nfc-contactless-smart-card-reader/) の「Drivers」タブを開く
2. お使いのOSに合ったドライバをダウンロードしてインストール
   - **Mac:** `.pkg` ファイルをダブルクリック → 画面の指示に従う
   - **Windows:** `.exe` ファイルをダブルクリック → 画面の指示に従う
3. ACR122UをUSBケーブルでパソコンに接続（緑色のLEDが点灯すればOK）

> **Mac で書き込みが不安定な場合:**  
> macOS標準のNFCデーモンと競合することがあります。ターミナルを開いて以下を実行してください:
> ```
> sudo killall -9 com.apple.ifdreader
> ```

### Step 3: ターミナル（コマンドプロンプト）を開く

コマンドを入力するための画面を開きます。

- **Mac:** Finder →「アプリケーション」→「ユーティリティ」→「ターミナル」を開く  
  （または Spotlight で「ターミナル」と検索）
- **Windows:** スタートメニューで「cmd」と検索 →「コマンドプロンプト」を開く

以降の手順はすべてこの画面にコマンドを入力して実行します。

### Step 4: このツールをダウンロードしてセットアップ

ターミナル（コマンドプロンプト）に以下を1行ずつ貼り付けて Enter を押してください。

```bash
# ダウンロード
git clone https://github.com/<your-username>/nfc-batch-writer.git

# ダウンロードしたフォルダに移動
cd nfc-batch-writer

# Python仮想環境を作成（初回のみ）
python3 -m venv .venv

# 仮想環境を有効化（毎回ツールを使う前に実行）
source .venv/bin/activate        # Mac の場合
# .venv\Scripts\activate         # Windows の場合

# 必要なライブラリをインストール（初回のみ）
pip install -r requirements.txt
```

> **Mac で `pip install` がエラーになる場合:**
> ```bash
> xcode-select --install    # 開発者ツールをインストール
> brew install swig          # swigをインストール（Homebrewが必要）
> pip install pyscard        # 再インストール
> ```

### Step 5: ツールを起動して書き込み開始

```bash
# 仮想環境を有効化（Step 4 から続けている場合は不要）
source .venv/bin/activate        # Mac
# .venv\Scripts\activate         # Windows

# ブラウザUIを起動
python3 -m src.web_main
```

ターミナルに `Uvicorn running on http://127.0.0.1:8787` と表示されたら成功です。

1. ブラウザ（Chrome, Safari など）で **http://127.0.0.1:8787** を開く
2. **モード選択** — 「単一URL」か「CSV」を選ぶ
3. **リーダー選択** — 「PC/SC」を選ぶ（ACR122Uが自動で認識されます）
4. **「開始」ボタン** を押す
5. **NFCタグをリーダーにかざす**（3秒以上しっかり当てたまま待つ）
6. 「ピッ」と鳴ったら書き込み成功 → タグを離して次のタグをかざす

> **リーダーなしで試したい場合:** リーダー選択で「Mock」を選べば、リーダーがなくても画面の操作を試せます。

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
