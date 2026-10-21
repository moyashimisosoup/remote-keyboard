# Remote Keyboard

**iPhoneの標準日本語キーボードから、自宅のWindows PCへ文字入力する軽量Webアプリ。**

公開しているのはソースコードです。PC側の受信サーバーはローカルホストのみに待ち受け、**Tailscale ServeによるTailnet内HTTPS接続**でiPhoneから利用します。第三者が開ける公開キーボードではありません。GitHub Pagesやクラウドサーバーは不要です。

> v0.1 試作。HTTP受信・認証・重複送信防止の自動テストは実施済み。実際のiPhone Safari → Windowsメモ帳の入力は未検証です。

## 初めて使う場合

### 1. Windows PCで準備

- [このリポジトリのZIP](https://github.com/moyashimisosoup/remote-keyboard/archive/refs/heads/main.zip) をWindows PCでダウンロードして解凍します。
- [Python 3](https://www.python.org/downloads/windows/) と [Tailscale](https://tailscale.com/download/windows) が必要です。Python追加パッケージは必要ありません。
- 解凍したフォルダの `start-windows.cmd` をダブルクリック。黒い画面に出る **6桁の Pairing PIN** を確認します。PINは30分有効。停止はウィンドウを閉じるか Ctrl+C です。
- 同じPCのブラウザで `http://127.0.0.1:8787` を開ければ受信プログラムが起動しています。

### 2. PCでTailscale Serveを起動

別のPowerShellで、先に既存のServe設定を確認します。

```powershell
tailscale status
tailscale serve status
```

**既にServeがある場合は設定を上書きしないでください。** 競合がなければ以下を実行します。

```powershell
tailscale serve 8787
```

このコマンドは前面で実行します。表示された **https://...ts.net** のURLを使います。Tailscale Serve用HTTPS証明書の有効化が求められる場合があります。

**禁止**: `tailscale funnel`、ルーターのポート開放、受信プログラムを `0.0.0.0` に公開する変更。

### 3. iPhoneで文字入力

1. iPhoneでもTailscaleを接続し、PCと同じTailnetに参加します。
2. SafariでPCに表示された **https://...ts.net** のURLを開きます。**github.ioの公開URLではありません。**
3. PCの黒い画面の6桁PINを入力して「接続」を押します。
4. PCでメモ帳を開き、文字を入力する場所をクリックします。
5. iPhoneで「入力を開始」を押し、標準キーボードで入力します。英数字は入力ごと、日本語は変換確定後に送られます。
6. 終わったら「入力を停止」。Windows側の受信プログラムとTailscale Serveも終了できます。

入力先はPCで**現在フォーカスしているウィンドウ**です。PCの画面をiPhoneに転送する機能ではありません。PCのロック画面や管理者権限のアプリなどは操作対象外です。

## 搭載機能

- iPhone Safariの標準キーボードと日本語IME変換確定の検知
- Unicode文字送信、Enter / Backspace / Tab / Escape
- PINペアリング、セッションCookie、誤入力防止の開始・停止、35秒の入力許可タイムアウト
- 同一イベントIDの再送時の重複抑止、送信成否が曖昧な場合の再確認UI
- 受信は `127.0.0.1:8787` に限定、入力内容のディスク保存なし

## 制約・注意

- 本アプリでは**PCの画面や入力先の実際のテキストを取得できません**。スマホの入力欄はPCの内容と双方向同期されません。
- 日本語変換や絵文字、Backspace、文字の選択・置換ではWindowsアプリとiPhoneの差によりズレる場合があります。
- 通信失敗時に操作を再試行する設計ですが、PC側の部分入力やプロセス再起動では完全な「一度だけ」を保証できません。
- PCのフォーカスが別アプリに移ると意図しない場所へ入力され得ます。パスワードなど秘密情報の入力には使わないでください。
- ペアリングコード、Tailnetの接続URL、端末情報、秘密鍵、入力した文章をIssue・GitHubコミットへ貼らないでください。
- v0.1はWindowsでの自動常駐と実機受入検証が未完了です。

## 開発

標準ライブラリのみでテストできます。

```sh
python -m unittest discover -s tests -v
```

コード: `remote_keys.py`（Windows受信・SendInput）, `index.html` / `style.css` / `app.js`（iPhone UI）, `start-windows.cmd`（Windows起動）。

プロジェクト方針は [AGENTS.md](AGENTS.md)、今後の検証は [docs/ROADMAP.md](docs/ROADMAP.md) を参照してください。
