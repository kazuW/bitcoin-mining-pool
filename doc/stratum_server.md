# StratumServerクラス解説

`StratumServer`クラスはStratumプロトコルを実装し、マイナーとの通信を担当します。マイナーの接続管理、認証、メッセージの処理などを行います。

## 初期化と起動

### `__init__(self, pool, config)`
- **説明**: StratumServerクラスのコンストラクタ
- **引数**: 
  - `pool`: Poolクラスのインスタンス
  - `config`: 設定情報を持つConfigParserオブジェクト
- **処理内容**:
  - サーバー設定の読み込み（ホスト、ポート）
  - クライアント接続管理のためのデータ構造初期化
  - 接続数制限のためのセマフォア初期化
  - 難易度設定の読み込み（`difficulty`, `accept_suggested_difficulty`）

### `start(self)`
- **説明**: Stratumサーバーを起動する
- **処理内容**:
  - 指定されたホストとポートでTCPサーバーを起動
  - バックグラウンドタスクの開始（モニタリング、ジョブブロードキャスト）
  - シグナルハンドラの設定

## クライアント接続管理

### `handle_client(self, reader, writer)`
- **説明**: 新しいクライアント接続があった時に呼び出されるコールバック
- **引数**:
  - `reader`: StreamReaderオブジェクト（クライアントからの読み取り用）
  - `writer`: StreamWriterオブジェクト（クライアントへの書き込み用）
- **処理内容**:
  - 接続数制限のチェック
  - クライアントIDの生成と情報保存
  - クライアントメッセージ処理の開始

### `_process_client_messages(self, client_id, reader, writer)`
- **説明**: クライアントからのメッセージを読み取り、処理するループ
- **引数**:
  - `client_id`: クライアントの一意識別子
  - `reader`: StreamReaderオブジェクト
  - `writer`: StreamWriterオブジェクト
- **処理内容**:
  - クライアントからのデータ読み取り
  - JSONデコードとメッセージの処理
  - レスポンスの送信
  - エラーハンドリング

## メッセージ処理

### `process_message(self, client_id, message)`
- **説明**: クライアントからのStratumプロトコルメッセージを処理
- **引数**:
  - `client_id`: クライアントの一意識別子
  - `message`: 受信したJSONメッセージ
- **戻り値**: クライアントに返送するレスポンス
- **処理内容**:
  - メッセージの種類に応じた処理分岐
  - `mining.subscribe`: 購読処理
  - `mining.authorize`: 認証処理
  - `mining.configure`: 機能ネゴシエーション（Version Rollingなど）
  - `mining.suggest_difficulty`: 難易度提案の処理（設定により採用/無視）
  - `mining.submit`: シェア提出処理

### `is_valid_bitcoin_address(self, address)`
- **説明**: ビットコインアドレスの基本的な検証
- **引数**:
  - `address`: 検証するビットコインアドレス
- **戻り値**: アドレスが有効な場合はTrue、そうでない場合はFalse
- **処理内容**:
  - アドレス形式のチェック（テストネットSegwitアドレスのみ有効）

## ジョブ配布と通知

### `broadcast_jobs(self)`
- **説明**: 新しいジョブを全クライアントにブロードキャストするバックグラウンドタスク
- **処理内容**:
  - 新しいジョブの検出
  - ジョブ通知メッセージの作成
  - 全認証済みクライアントへの送信

### `_send_notification(self, client_id, notification)`
- **説明**: 特定のクライアントに通知を送信
- **引数**:
  - `client_id`: クライアントの一意識別子
  - `notification`: 送信する通知メッセージ
- **処理内容**:
  - クライアントのWriterを使用して通知を送信
  - エラーハンドリング

## モニタリングと管理

### `monitor_clients(self)`
- **説明**: クライアント状態を定期的に監視し、統計情報を収集・表示する
- **処理内容**:
  - 接続数、認証済みマイナー数のカウント
  - ワーカー別、アドレス別の統計収集
  - システムリソース使用状況の確認

### `shutdown(self, signal_name=None)`
- **説明**: サーバーを安全にシャットダウンする
- **引数**:
  - `signal_name`: シグナル名（オプション）
- **処理内容**:
  - 全クライアントにシャットダウン通知を送信
  - 接続のクローズ
  - イベントループの停止