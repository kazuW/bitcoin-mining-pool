import asyncio
import socket
import json
from configparser import ConfigParser
import uuid
import time
import signal
import platform
import logging

class StratumServer:
    def __init__(self, pool, config):
        self.host = config.get('STRATUM', 'host', fallback='127.0.0.1')
        self.port = config.getint('STRATUM', 'port', fallback=3333)
        self.pool = pool
        self.server = None
        self.clients = {}  # クライアント接続を管理
        self.max_connections = config.getint('STRATUM', 'max_connections', fallback=100)
        self.connection_semaphore = asyncio.Semaphore(self.max_connections)
        self.loop = asyncio.get_event_loop()
        self.logger = logging.getLogger('stratum')  # loggerを初期化
        # 難易度設定を読み込む
        # STRATUMセクションから難易度を読み込む
        self.default_difficulty = config.getfloat('STRATUM', 'difficulty', fallback=1.0)
        self.accept_suggested_difficulty = config.getboolean('STRATUM', 'accept_suggested_difficulty', fallback=True)

        
        try:
            self.setup_signal_handlers()
        except NotImplementedError:
            print("Signal handlers not supported on Windows.")
        except Exception as e:
            print(f"Warning: Unable to set up signal handlers: {e}")

    async def handle_client(self, reader, writer):
        # 接続数制限の実装
        if not self.connection_semaphore.locked():
            async with self.connection_semaphore:
                client_id = str(uuid.uuid4()).split('-')[0]  # 例: "bf3796c2"
                addr = writer.get_extra_info('peername')
                print(f"Connection from {addr}, assigned ID: {client_id}")
                
                # クライアント情報の保存
                self.clients[client_id] = {
                    'reader': reader,
                    'writer': writer,
                    'addr': addr,
                    'last_activity': time.time(),
                    'authorized': False,
                    'worker_name': None
                }
                
                try:
                    await self._process_client_messages(client_id, reader, writer)
                except asyncio.CancelledError:
                    print(f"Client {client_id} task cancelled")
                except ConnectionResetError as e:
                    # 接続リセットエラーを明示的に処理
                    print(f"Client {client_id} connection reset: {e}")
                except Exception as e:
                    print(f"Error handling client {client_id}: {e}")
                finally:
                    # クリーンアップ
                    if client_id in self.clients:
                        print(f"Cleaning up client {client_id}")
                        try:
                            del self.clients[client_id]
                        except KeyError:
                            print(f"Client {client_id} already removed from clients dict")
                    
                    try:
                        writer.close()
                        if not writer.is_closing():
                            await writer.wait_closed()
                    except Exception as e:
                        print(f"Error during connection cleanup for {client_id}: {e}")
                    
                    print(f"Connection closed: {client_id}")
        else:
            # 最大接続数に達した場合
            writer.write(json.dumps({"id": None, "error": [503, "Too many connections", None]}).encode() + b'\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()

    async def _process_client_messages(self, client_id, reader, writer):
        try:
            while True:
                try:
                    # データ読み取り
                    data = await reader.readline()
                    if not data:
                        print(f"Client {client_id} disconnected")
                        break
                    
                    # クライアントのアクティビティを更新
                    self.clients[client_id]['last_activity'] = time.time()
                    
                    # メッセージ処理
                    try:
                        decoded_data = data.decode().strip()
                        print(f"<<< Received from client {client_id}: {decoded_data}")
                        message = json.loads(decoded_data)
                        
                        # IDなしのメッセージはNotificationとして扱う
                        if 'id' not in message:
                            print(f"Client {client_id}: Received notification: {message.get('method')}")
                            # 通知の処理（必要に応じて）
                            continue
                        
                        # 通常のリクエスト処理
                        response = await self.process_message(client_id, message)
                        
                        # レスポンス送信 - Noneの場合は送信しない
                        if response is not None:  # 追加: Noneの場合は送信しない
                            encoded_response = (json.dumps(response) + '\n').encode()
                            print(f">>> Sending to client {client_id}: {json.dumps(response)}")
                            writer.write(encoded_response)
                            await writer.drain()
                        
                    except json.JSONDecodeError as e:
                        print(f"Client {client_id}: Invalid JSON: {e}")
                        writer.write(json.dumps({"id": None, "error": [20, "Invalid JSON", None]}).encode() + b'\n')
                        await writer.drain()
                        
                    except Exception as e:
                        print(f"Error processing message for client {client_id}: {e}")
                        # ID付きメッセージの場合はそのIDを使用してエラーを返す
                        message_id = message.get('id') if 'message' in locals() and isinstance(message, dict) else None
                        writer.write(json.dumps({"id": message_id, "error": [20, f"Internal error: {str(e)}", None], "result": None}).encode() + b'\n')
                        await writer.drain()
                        
                except asyncio.CancelledError:
                    print(f"Client {client_id} task cancelled")
                    break
                    
                except ConnectionError as e:
                    print(f"Connection error with client {client_id}: {e}")
                    break
                except Exception as e:
                    print(f"Error processing client {client_id} message: {e}")
                    continue
        except Exception as e:
            print(f"Fatal error in client {client_id} processing: {e}")
        finally:
            # クリーンアップ
            if client_id in self.clients:
                print(f"Cleaning up client {client_id}")
                try:
                    del self.clients[client_id]
                except KeyError:
                    print(f"Client {client_id} already removed from clients dict")
            try:
                writer.close()
                if not writer.is_closing():
                    await writer.wait_closed()
            except Exception as e:
                print(f"Error closing writer for client {client_id}: {e}")
            print(f"Connection closed: {client_id}")

    async def process_message(self, client_id, message):
        """
        Stratumプロトコルのメッセージを処理する
        """
        method = message.get("method")
        params = message.get("params", [])
        message_id = message.get("id")
        
        # クライアント情報を取得
        client = self.clients.get(client_id)
        if not client:
            return {"id": message_id, "error": [24, "Client not found", None], "result": None}
        
        print(f"Client {client_id}: Received {method} request")
        
        # 各種Stratumメソッドの処理
        if method == "mining.subscribe":
            # マイナーの登録処理
            session_id = client_id[:8]  # UUIDの一部を使用
            subscription_details = [
                ["mining.set_difficulty", session_id],
                ["mining.notify", session_id]
            ]
            # 固定難易度とエクストラノンスサイズ
            extranonce1 = session_id + "00"  # セッションIDを利用
            extranonce2_size = 4
            
            client['subscribed'] = True
            client['extranonce1'] = extranonce1
            client['extranonce2_size'] = extranonce2_size
            
            return {
                "id": message_id,
                "result": [subscription_details, extranonce1, extranonce2_size],
                "error": None
            }
        
        elif method == "mining.authorize":
            worker_name = params[0] if params else None
            bitcoin_address = worker_name
            password = params[1] if len(params) > 1 else None
            
            print(f"Client {client_id}: Received mining.authorize request")
            
            # ワーカー名とアドレスの検証
            authorized = await self.validate_worker(worker_name, client_id)
            
            if authorized:
                client['authorized'] = True
                client['worker_name'] = worker_name
                client['bitcoin_address'] = bitcoin_address
                
                # 1. 認証成功レスポンス
                auth_response = {"id": message_id, "result": True, "error": None}
                writer = self.clients[client_id]['writer']
                writer.write((json.dumps(auth_response) + '\n').encode())
                await writer.drain()
                
                # 待機を増やす
                await asyncio.sleep(1.0)  # 1秒待機
                
                # 2. 難易度設定
                difficulty_to_use = self.default_difficulty  # 設定ファイルの値を使用
                client['difficulty'] = difficulty_to_use
                print(f"Setting initial difficulty for client {client_id}: {difficulty_to_use}")
                difficulty_notification = {
                    "id": None,
                    "method": "mining.set_difficulty",
                    "params": [difficulty_to_use]
                }
                writer.write((json.dumps(difficulty_notification) + '\n').encode())
                await writer.drain()
                
                # 重要: 難易度設定後、十分な待機時間を設ける
                await asyncio.sleep(2.0)  # 2秒待機
                
                # 3. ジョブ通知
                current_job = await self.pool.get_current_job()
                if current_job:
                    # マークルブランチの制限 - 8個に制限
                    # merkle_branches = current_job['merkle_branches'][:8]  # 15から8に減らす
                    merkle_branches = current_job['merkle_branches']

                    ntime = format(current_job['ntime'], '08x') 
                    
                    # job_idをより標準的な形式に変更
                    job_id = format(current_job['job_id'], '016x')  # 16文字の16進数文字列に
                    
                    job_notification = {
                        "params": [  # 順序を変更："params"を最初に
                            job_id,
                            current_job['prevhash'],
                            current_job['coinbase1'],
                            current_job['coinbase2'],
                            merkle_branches,
                            format(current_job['version'], '08x'),
                            current_job['nbits'],
                            ntime,  # すでに16進数文字列形式
                            False  # 常にfalseを使用
                        ],
                        "id": None,
                        "method": "mining.notify"  # methodを最後に
                    }
                    
                    # ジョブ詳細をログに記録
                    print(f"Job notification: {json.dumps(job_notification)}")
                    print(f"coinbase1: {current_job['coinbase1']}")
                    print(f"coinbase2: {current_job['coinbase2']}")
                    
                    # ジョブ通知を直接送信
                    print(f">>> Sending to client {client_id}: {json.dumps(job_notification)}")
                    writer.write((json.dumps(job_notification) + '\n').encode())
                    await writer.drain()
                
                # 既に直接メッセージを送信したのでNoneを返す
                return None
        
        elif method == "mining.submit":
            # シェア提出処理
            if not client['authorized']:
                return {"id": message_id, "error": [24, "Unauthorized worker", None], "result": None}
            
            if len(params) < 5:
                return {"id": message_id, "error": [21, "Missing parameters", None], "result": None}
            
            worker_name = params[0]
            job_id, extranonce2, ntime, nonce = params[1:5]
            version = params[5] if len(params) > 5 else None
            bitcoin_address = client['bitcoin_address']
            
            # デバッグ情報を追加
            print(f"Mining submit parameters:")
            print(f"  worker_name: {params[0] if len(params) > 0 else 'None'}")
            print(f"  job_id: {params[1] if len(params) > 1 else 'None'}")
            print(f"  extranonce2: {params[2] if len(params) > 2 else 'None'}")
            print(f"  ntime: {params[3] if len(params) > 3 else 'None'}")
            print(f"  nonce: {params[4] if len(params) > 4 else 'None'}")
            print(f"  version: {params[5] if len(params) > 5 else 'None'}")
            print(f"  client extranonce1: {client.get('extranonce1', 'None')}")
            print(f"  bitcoin_address: {client.get('bitcoin_address', 'None')}")
            
            try:
                # 正しいパラメータ順序でvalidate_shareを呼び出し
                valid_share = await self.pool.validate_share(
                    worker_name,           # 第1引数
                    bitcoin_address,       # 第2引数  
                    job_id,               # 第3引数
                    client['extranonce1'], # 第4引数
                    extranonce2,          # 第5引数
                    ntime,                # 第6引数
                    nonce,                # 第7引数
                    version,              # 第8引数
                    None,                 # version_mask (optional)
                    client.get('difficulty', self.default_difficulty) # difficulty (new argument)
                )
                
                if valid_share.get('valid'):
                    print(f"Client {client_id}: Valid share submitted by {worker_name}")
                    
                    if valid_share.get('block_found'):
                        print(f"BLOCK FOUND! By {worker_name}")
                    
                    return {"id": message_id, "result": True, "error": None}
                else:
                    reason = valid_share.get('reason', 'Share rejected')
                    print(f"Client {client_id}: Invalid share - {reason}")
                    return {"id": message_id, "result": False, "error": [21, reason, None]}
                    
            except Exception as e:
                print(f"Error validating share: {e}")
                import traceback
                traceback.print_exc()
                return {"id": message_id, "error": [20, "Internal error during validation", None], "result": None}
        
        elif method == "mining.get_transactions":
            # トランザクション情報リクエスト（オプション）
            current_job = await self.pool.get_current_job()
            if current_job and 'transactions' in current_job:
                return {"id": message_id, "result": current_job['transactions'], "error": None}
            else:
                return {"id": message_id, "result": [], "error": None}
        
        elif method == "client.get_version":
            # クライアントバージョン情報（オプション）
            return {
                "id": message_id,
                "result": "Bitcoin Mining Pool v0.1.0",
                "error": None
            }
        
        elif method == "client.reconnect":
            # 再接続要求 - 通常はロードバランシングなどで使用
            return {"id": message_id, "result": True, "error": None}
        
        elif method == "mining.configure":
            # 拡張機能の設定
            supported_versions = {}
            supported_features = {}
            
            requested_features = params[0] if len(params) > 0 else []
            feature_params = params[1] if len(params) > 1 else {}
            
            # バージョンローリングのサポート
            if "version-rolling" in requested_features and isinstance(feature_params, dict) and "version-rolling.mask" in feature_params:
                mask = feature_params["version-rolling.mask"]
                supported_features["version-rolling"] = True
                supported_versions["version-rolling.mask"] = mask
                print(f"Enabled version-rolling with mask: {mask}")
            
            return {
                "id": message_id,
                "result": {
                    "version-rolling": supported_features.get("version-rolling", False),
                    "version-rolling.mask": supported_versions.get("version-rolling.mask", "00000000")
                },
                "error": None
            }
        
        elif method == "mining.suggest_difficulty":
            # マイナーが提案する難易度
            suggested_difficulty = params[0] if len(params) > 0 else 1000
            
            # クライアント記録を更新
            client['suggested_difficulty'] = suggested_difficulty

            # 設定に基づいて難易度を決定
            if self.accept_suggested_difficulty:
                difficulty_to_use = suggested_difficulty
                print(f"Client {client_id} suggested difficulty: {suggested_difficulty} (Accepted)")
            else:
                difficulty_to_use = self.default_difficulty
                print(f"Client {client_id} suggested difficulty: {suggested_difficulty} (Ignored, using default: {difficulty_to_use})")
            
            # Store the difficulty in the client object for validation
            client['difficulty'] = difficulty_to_use
            
            # デバッグ情報
            print(f"Using difficulty: {difficulty_to_use}")

            
            # 難易度変更メッセージを直接送信
            difficulty_notification = {
                "id": None,
                "method": "mining.set_difficulty",
                "params": [difficulty_to_use]
            }
            
            # メッセージを送信
            print(f">>> Sending updated difficulty to client {client_id}: {json.dumps(difficulty_notification)}")
            writer = self.clients[client_id]['writer']
            writer.write((json.dumps(difficulty_notification) + '\n').encode())
            await writer.drain()
            
            # 応答を返す
            return {
                "id": message_id,
                "result": True,
                "error": None
            }
        
        else:
            # 未知のメソッド
            print(f"Client {client_id}: Unknown method {method}")
            return {"id": message_id, "error": [20, f"Unknown method {method}", None], "result": None}

    async def start(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        print(f'Serving on {self.host}:{self.port}')
        
        # 監視・管理タスクの開始
        self.tasks = [
            asyncio.create_task(self.monitor_clients()),
            asyncio.create_task(self.broadcast_jobs()),
            asyncio.create_task(self.cleanup_inactive_clients())
        ]
        
        try:
            async with self.server:
                await asyncio.gather(
                    self.server.serve_forever(),
                    *self.tasks
                )
        except asyncio.CancelledError:
            # 全タスクをキャンセル
            for task in self.tasks:
                task.cancel()
            # 残っているタスクを終了させる
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def cleanup_inactive_clients(self):
        """非アクティブなクライアントを定期的に切断する"""
        while True:
            await asyncio.sleep(60)  # 1分ごとにチェック
            current_time = time.time()
            inactive_timeout = 300  # 5分間アクティビティがなければ切断
            
            inactive_clients = []
            for client_id, client_data in self.clients.items():
                if current_time - client_data['last_activity'] > inactive_timeout:
                    inactive_clients.append(client_id)
            
            for client_id in inactive_clients:
                try:
                    print(f"Closing inactive connection: {client_id}")
                    client_data = self.clients[client_id]
                    client_data['writer'].close()
                    # 実際の切断はhandle_clientのfinallyブロックで処理される
                except Exception as e:
                    print(f"Error closing inactive connection {client_id}: {e}")

    async def broadcast_jobs(self):
        """新しいジョブを全クライアントにブロードキャストするバックグラウンドタスク"""
        last_job_id = None
        
        while True:
            try:
                # 現在のジョブを取得
                current_job = await self.pool.get_current_job()
                
                if not current_job:
                    await asyncio.sleep(1)
                    continue
                    
                if current_job['job_id'] == last_job_id:
                    # 同じジョブなのでスキップ
                    await asyncio.sleep(10)
                    continue
                    
                # 新しいジョブを検出
                last_job_id = current_job['job_id']
                
                # マークルブランチのサイズが大きすぎる場合は制限する
                # merkle_branches = current_job['merkle_branches'][:8]  # 常に最大8に制限
                merkle_branches = current_job['merkle_branches']

                ntime = format(current_job['ntime'], '08x') 
                
                # job_idをより標準的な形式に変更
                job_id = format(current_job['job_id'], '016x')  # 16文字の16進数文字列に

                # ジョブ通知メッセージを作成
                job_notification = {
                    "params": [
                        job_id,
                        current_job['prevhash'],
                        current_job['coinbase1'],
                        current_job['coinbase2'],
                        merkle_branches,
                        format(current_job['version'], '08x'),  # 16進数文字列に変換
                        current_job['nbits'],
                        ntime,
                        False
                    ],
                    "id": None,
                    "method": "mining.notify"
                }
                
                print(f"=== Broadcasting job {current_job['job_id']} to all clients ===")
                print(f"Job details: {json.dumps(job_notification)}")
                
                # 全認証済みクライアントに送信
                for client_id, client in self.clients.items():
                    if client.get('authorized', False):
                        await self._send_notification(client_id, job_notification)
                        
                # より長めの間隔でブロードキャスト
                await asyncio.sleep(60)  # 1分待機
            except Exception as e:
                print(f"Error in job broadcast: {e}")
                await asyncio.sleep(5)

    async def _send_notification(self, client_id, notification):
        """クライアントに通知を送信し、エラーを適切に処理"""
        try:
            client_data = self.clients.get(client_id)
            if client_data and not client_data.get('disconnected', False):
                # 切断済みでなければ送信
                print(f">>> Sending to client {client_id}: {json.dumps(notification)}")
                client_data['writer'].write((json.dumps(notification) + '\n').encode())
                await client_data['writer'].drain()
                
                # 最終メッセージタイムスタンプを更新
                client_data['last_message_sent'] = time.time()
        except ConnectionError:
            print(f"Connection lost for client {client_id} during notification")
            self._mark_client_disconnected(client_id)
        except Exception as e:
            print(f"Error sending notification to client {client_id}: {e}")

    async def _send_message(self, client_id, message):
        """クライアントにメッセージを送信する"""
        try:
            client_data = self.clients.get(client_id)
            if client_data and not client_data.get('disconnected', False):
                # 切断済みでなければ送信
                print(f">>> Sending to client {client_id}: {json.dumps(message)}")
                client_data['writer'].write((json.dumps(message) + '\n').encode())
                await client_data['writer'].drain()
                
                # 最終メッセージタイムスタンプを更新
                client_data['last_message_sent'] = time.time()
                return True
            return False
        except ConnectionError:
            print(f"Connection lost for client {client_id} during message")
            self._mark_client_disconnected(client_id)
            return False
        except Exception as e:
            print(f"Error sending message to client {client_id}: {e}")
            return False

    def _mark_client_disconnected(self, client_id):
        """クライアントを切断済みとしてマーク"""
        if client_id in self.clients:
            self.clients[client_id]['disconnected'] = True
            print(f"Marked client {client_id} as disconnected")

    def setup_signal_handlers(self):
        """シグナルハンドラーを設定"""
        # Windows環境では信号処理が制限されているので条件分岐
        if platform.system() != 'Windows':
            self.loop.add_signal_handler(
                signal.SIGINT, lambda: asyncio.create_task(self.shutdown('SIGINT')))
            self.loop.add_signal_handler(
                signal.SIGTERM, lambda: asyncio.create_task(self.shutdown('SIGTERM')))
        else:
            # Windows環境では代替手段（キーボード割り込みなど）を検討
            print("Signal handlers not supported on Windows.")

    async def shutdown(self, signal_name=None):
        """サーバーを安全にシャットダウン"""
        print(f"Received exit signal {signal_name}..." if signal_name else "Shutting down...")
        
        # サーバーの新規接続受付を停止
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        # 実行中のタスクをキャンセル
        for task in self.tasks:
            task.cancel()
        
        # 既存の接続をクリーンアップ
        close_tasks = []
        for client_id, client_data in self.clients.items():
            try:
                client_data['writer'].write(json.dumps({
                    "id": None, 
                    "method": "server.shutdown", 
                    "params": ["Server is shutting down"]
                }).encode() + b'\n')
                await client_data['writer'].drain()
                client_data['writer'].close()
                close_tasks.append(client_data['writer'].wait_closed())
            except:
                pass
        
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        
        # イベントループを停止
        self.loop.stop()

    async def monitor_clients(self):
        """クライアント状態を定期的に監視し、統計情報を収集・表示する"""
        while True:
            await asyncio.sleep(30)  # 30秒ごとに監視
            
            # 統計情報の収集
            total_clients = len(self.clients)
            authorized_clients = sum(1 for client in self.clients.values() if client['authorized'])
            
            # ワーカー別の統計
            worker_stats = {}
            for client in self.clients.values():
                if client['authorized'] and client['worker_name']:
                    worker_name = client['worker_name']
                    if worker_name not in worker_stats:
                        worker_stats[worker_name] = 0
                    worker_stats[worker_name] += 1
            
            # 統計情報の表示
            print(f"--- Client Monitor Status ---")
            print(f"Total connections: {total_clients}")
            print(f"Authorized miners: {authorized_clients}")
            print(f"Workers online: {len(worker_stats)}")
            
            # システムリソースの使用状況確認（オプション）
            try:
                import psutil
                process = psutil.Process()
                memory_info = process.memory_info()
                cpu_percent = process.cpu_percent()
                print(f"Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB")
                print(f"CPU usage: {cpu_percent:.1f}%")
            except ImportError:
                pass  # psutilが利用できない場合はスキップ
            
            print("----------------------------")
            
            # 必要に応じてログにも記録
            # self.logger.info(f"Monitor status: {total_clients} connections, {authorized_clients} authorized")

    def is_valid_bitcoin_address(self, address):
        """
        テストネットのSegwitアドレスのみを有効とする検証を行う
        
        テストネットのSegwitアドレスは 'tb1' で始まり、
        長さは通常14〜74文字の範囲です。
        """
        # テストネットのSegwitアドレス (tb1で始まる)のみを許可
        if address.startswith('tb1') and len(address) >= 14 and len(address) <= 74:
            return True
        
        # その他のアドレス形式は全て無効とする
        print(f"Address {address} rejected: Only testnet Segwit addresses (tb1...) are accepted")
        return False

    def print_client_monitor_status(self):
        # 切断済みクライアントを除外
        active_clients = {cid: c for cid, c in self.clients.items() if not c.get('disconnected', False)}
        total_connections = len(active_clients)
        authorized_miners = sum(1 for c in active_clients.values() if c.get('authorized'))
        workers_online = sum(1 for c in active_clients.values() if c.get('worker_name'))
        print('--- Client Monitor Status ---')
        print(f'Total connections: {total_connections}')
        print(f'Authorized miners: {authorized_miners}')
        print(f'Workers online: {workers_online}')
        print('----------------------------')

    async def handle_authorize(self, client_id, message):
        """ワーカー認証を処理"""
        worker_name = message['params'][0]
        password = message['params'][1]
        
        # ワーカー名のフォーマットチェック（例：アドレス）
        # 実際の環境ではもっと厳密な検証が必要
        is_valid = True  # 仮の実装：すべてのワーカーを許可
        
        if is_valid:
            self.pool.register_worker(client_id, worker_name)
            await self.send_success(client_id, message['id'])
            # 難易度を設定
            await self.send_difficulty(client_id, self.default_difficulty)
            # 最新のジョブを送信
            await self.send_job(client_id)
        else:
            await self.send_error(client_id, message['id'], 24, "Unauthorized worker")
        
        return is_valid

    async def validate_worker(self, worker_name, client_id=None, password=None):
        """ワーカー名とパスワードを検証する"""
        # 簡易的な実装：すべてのワーカーを許可
        if worker_name:
            # ワーカー登録
            if client_id:
                self.pool.register_worker(client_id, worker_name)
            else:
                print(f"Warning: No client_id provided for worker {worker_name}")
            return True
        return False

    def generate_extranonce1(self):
        """extranonce1を生成する（10文字のランダム16進数）"""
        import random
        return f"{random.randint(0, 0xffffffffff):010x}"

def main():
    config = ConfigParser()
    config.read('config/config.ini')
    
    host = config.get('stratum', 'host', fallback='127.0.0.1')
    port = config.getint('stratum', 'port', fallback=3333)
    
    pool = None  # Replace with actual pool instance
    server = StratumServer(host, port, pool)
    
    asyncio.run(server.start())

if __name__ == "__main__":
    main()