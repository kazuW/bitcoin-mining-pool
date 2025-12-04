# Poolクラス解説

`Pool`クラスはマイニングプールのコア機能を提供し、ブロックテンプレートの管理、シェアの検証、報酬の計算など、プールの中心的な処理を担当します。

## 初期化と起動

### `__init__(self, config)`
- **説明**: Poolクラスのコンストラクタ
- **引数**: 
  - `config`: 設定情報を持つConfigParserオブジェクト
- **処理内容**:
  - マイナー情報を保持する辞書の初期化
  - BitcoinRPCクライアントの初期化
  - ZMQ接続の設定
  - データベース接続の設定

### `start(self)`
- **説明**: プールを起動し、必要なタスクを開始する
- **処理内容**:
  - データベース接続の確立
  - 初期ブロックテンプレートの取得
  - バックグラウンドタスクの開始（ブロックテンプレート更新、ZMQリスナー）

## ブロックテンプレート管理

### `block_template_updater(self)`
- **説明**: 定期的にブロックテンプレートを更新するバックグラウンドタスク
- **処理内容**:
  - 10秒ごとにブロックテンプレートを更新
  - エラー発生時はログに記録

### `update_block_template(self)`
- **説明**: Bitcoin Coreからgetblocktemplateを取得する
- **処理内容**:
  - BitcoinRPC経由でブロックテンプレートを取得
  - 現在のブロック高さと異なる場合、新しいジョブを作成
  - 新しいジョブを配布

### `zmq_listener(self)`
- **説明**: ZMQを使用してBitcoin Coreからの通知をリッスンする
- **処理内容**:
  - 「hashblock」イベントをサブスクライブ
  - 新しいブロックが検出されたらブロックテンプレートを更新

## ジョブ作成と配布

### `create_stratum_job(self, template, job_id)`
- **説明**: Bitcoin CoreのブロックテンプレートをStratum形式のジョブに変換する
- **引数**:
  - `template`: ブロックテンプレート情報
  - `job_id`: ジョブID
- **戻り値**: Stratumジョブ辞書

### `create_coinbase_part1(self, template)`
- **説明**: コインベーストランザクションの前半部分を作成
- **引数**:
  - `template`: ブロックテンプレート情報
- **戻り値**: コインベース前半の16進数文字列

### `create_coinbase_part2(self, template)`
- **説明**: コインベーストランザクションの後半部分を作成
- **引数**:
  - `template`: ブロックテンプレート情報
- **戻り値**: コインベース後半の16進数文字列

### `calculate_merkle_branches(self, transactions)`
- **説明**: マークルブランチの計算
- **引数**:
  - `transactions`: トランザクションリスト
- **戻り値**: マークルブランチのリスト

### `distribute_job(self, job)`
- **説明**: 全マイナーにジョブを配布
- **引数**:
  - `job`: 配布するジョブ情報
- **処理内容**:
  - ジョブをジョブリストに追加
  - 古いジョブを削除（最新5つのみ保持）
  - 全マイナーにジョブを送信

### `send_job_to_miner(self, miner_id, job)`
- **説明**: 特定のマイナーにジョブを送信
- **引数**:
  - `miner_id`: マイナーID
  - `job`: 送信するジョブ情報
- **処理内容**:
  - Stratumプロトコルに従ってジョブ通知を作成
  - 非同期でメッセージを送信

## マイナー管理

### `add_miner(self, miner_id, connection)`
- **説明**: マイナーをプールに追加
- **引数**:
  - `miner_id`: マイナーID
  - `connection`: 接続オブジェクト
- **処理内容**:
  - マイナー情報の初期化と保存
  - 現在のジョブがあれば即座に送信

### `remove_miner(self, miner_id)`
- **説明**: マイナーをプールから削除
- **引数**:
  - `miner_id`: マイナーID

## シェア検証とブロック提出

### `validate_share(self, worker_name, bitcoin_address, job_id, extranonce1, extranonce2, ntime, nonce, version, version_mask=None, difficulty=None)`
- **説明**: マイナーから提出されたシェアを検証するメソッド
- **引数**:
  - `worker_name`: ワーカー名
  - `bitcoin_address`: 支払い用ビットコインアドレス
  - `job_id`: ジョブID
  - `extranonce1`: エクストラノンス1（サーバーが提供）
  - `extranonce2`: エクストラノンス2（クライアント生成）
  - `ntime`: タイムスタンプ（16進数）
  - `nonce`: ノンス値（16進数）
  - `version`: バージョン（16進数）
  - `version_mask`: バージョンローリング用マスク（オプション）
  - `difficulty`: 検証に使用する難易度（オプション）
- **戻り値**:
  - 検証結果を含む辞書（有効かどうか、ブロックが見つかったかなど）
- **処理内容**:
  - ジョブの存在確認
  - タイミングチェック
  - 重複提出チェック
  - コインベーストランザクション構築
  - マークルルート計算（ckpool互換のflip_32処理を含む）
  - バージョンローリング処理（ASICBoost対応）
  - ブロックヘッダー構築（ckpool互換のflip_80処理を含む）
  - ハッシュ計算と難易度検証
  - 結果の記録と返却

### `submit_block(self, header_bytes, job, bitcoin_address, worker_name)`
- **説明**: ブロックをBitcoin Coreに提出
- **引数**:
  - `header_bytes`: ブロックヘッダーのバイト列
  - `job`: ジョブ情報
  - `bitcoin_address`: 発見者のビットコインアドレス
  - `worker_name`: 発見者のワーカー名
- **処理内容**:
  - ブロックの構築
  - Bitcoin RPCを使用してブロックを提出
  - 結果をログに記録
  - ブロック提出履歴を保存

### `record_share(self, worker_name, bitcoin_address, difficulty, block_found=False)`
- **説明**: シェア統計を記録
- **引数**:
  - `worker_name`: ワーカー名
  - `bitcoin_address`: ビットコインアドレス
  - `difficulty`: 難易度
  - `block_found`: ブロックが見つかったかどうか
- **処理内容**:
  - ワーカー統計の更新
  - データベースにシェアを記録（ソロマイニング用統計）
  - ブロック発見時の処理

## ヘルパーメソッド

### `double_sha256(self, data)`
- **説明**: データのdouble SHA-256ハッシュを計算
- **引数**:
  - `data`: ハッシュ化するデータ
- **戻り値**: ハッシュダイジェスト

### `difficulty_to_target(self, difficulty)`
- **説明**: 難易度からターゲット値を計算
- **引数**:
  - `difficulty`: 難易度
- **戻り値**: ターゲット整数値

### `bits_to_target(self, bits_hex)`
- **説明**: bitsフィールドからターゲット値を計算
- **引数**:
  - `bits_hex`: ビットフィールド（16進数）
- **戻り値**: ターゲット整数値