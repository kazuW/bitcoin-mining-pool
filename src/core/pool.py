import asyncio
import json
import hashlib
import time
import logging
import zmq
import zmq.asyncio
from typing import Dict, Any, List, Optional
from .bitcoin_rpc import BitcoinRPC
from utils.helper import bytes_to_hex, hex_to_bytes

class Pool:
    def __init__(self, config):
        self.config = config
        self.miners = {}
        self.jobs = []
        self.current_block = None
        self.current_job_id = 0
        
        # BitcoinRPCクライアントの初期化
        btc_config = config['BITCOIN']
        self.bitcoin_rpc = BitcoinRPC(
            rpc_user=btc_config['user'],
            rpc_password=btc_config['password'],
            rpc_host=btc_config['host'],
            rpc_port=int(btc_config['port'])
        )
        # print(f"Connecting to Bitcoin Core at {btc_config['host']}:{btc_config['port']}")

        # ZMQ設定
        self.zmq_url = f"tcp://{config['ZMQ']['host']}:{config['ZMQ']['port']}"
        # print(f"ZMQ URL: {self.zmq_url}")

        # ロギング設定
        self.logger = logging.getLogger('pool')

        # 統計情報の初期化
        self.worker_stats = {}
        self.submitted_shares = {}
        self.blocks_found = 0
        self.submitted_blocks = []

        # アドレス変換用ライブラリの事前インポート
        import bech32
        import base58
        self.bech32 = bech32
        self.base58 = base58

    async def start(self):
        """プールを起動し、必要なタスクを開始する"""
        self.logger.info("Starting mining pool...")
        
        # 初期ブロックテンプレートを取得
        await self.update_block_template()
        
        # バックグラウンドタスク開始
        asyncio.create_task(self.block_template_updater())
        asyncio.create_task(self.zmq_listener())
        
        self.logger.info("Mining pool started successfully")

    async def block_template_updater(self):
        """定期的にブロックテンプレートを更新するバックグラウンドタスク"""
        while True:
            try:
                await asyncio.sleep(10)  # 10秒ごとに更新
                await self.update_block_template()
            except Exception as e:
                self.logger.error(f"Error updating block template: {e}")

    async def update_block_template(self):
        """Bitcoin Coreからgetblocktemplateを取得する"""
        try:
            # BitcoinRPC経由でgetblocktemplateを取得
            template_params = {"rules": ["segwit"]}
            response = self.bitcoin_rpc.get_block_template(params=[template_params])
            
            if 'error' in response and response['error'] is not None:
                self.logger.error(f"Failed to get block template: {response['error']}")
                return
                
            template = response['result']
            if not template:
                self.logger.warning("Failed to get block template: Empty result")
                return
                
            # 現在のブロック高さと異なるか確認
            if not self.current_block or template['height'] != self.current_block['height']:
                self.current_block = template
                self.current_job_id += 1
                
                job = self.create_stratum_job(template, self.current_job_id)
                self.logger.info(f"New block template at height {template['height']}, job_id: {self.current_job_id}")
                
                # 新しいジョブを配布
                self.distribute_job(job)
        except Exception as e:
            self.logger.error(f"Failed to update block template: {e}")

    async def zmq_listener(self):
        """ZMQを使用してBitcoin Coreからの通知をリッスンする"""
        context = zmq.asyncio.Context()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.SUBSCRIBE, b"hashblock")
        socket.connect(self.zmq_url)
        
        self.logger.info(f"ZMQ listener connected to {self.zmq_url}")
        
        while True:
            try:
                topic, body, seq = await socket.recv_multipart()
                if topic == b"hashblock":
                    block_hash = bytes_to_hex(body)
                    self.logger.info(f"New block detected via ZMQ: {block_hash}")
                    
                    # 新しいブロックが見つかったら即座にテンプレート更新
                    await self.update_block_template()
            except Exception as e:
                self.logger.error(f"ZMQ listener error: {e}")
                await asyncio.sleep(1)  # エラー発生時の再接続遅延

    def create_stratum_job(self, template: Dict, job_id: int) -> Dict:
        """Bitcoin CoreのブロックテンプレートをStratum形式のジョブに変換する"""
        prevhash = template['previousblockhash']
        
        # 新しいcreate_coinbase_txメソッドを使用
        height = template['height']
        reward = template['coinbasevalue']
        address = self.config.get('POOL', 'address', fallback='tb1q6kr0xxz37ys0ajfjf2kv85hl48zf8g7grs40lu')
        
        coinbase_tx = self.create_coinbase_tx(height, reward, address)
        coinbase1 = coinbase_tx['coinbase1']
        coinbase2 = coinbase_tx['coinbase2']
        
        merkle_branches = self.calculate_merkle_branches(template['transactions'])
        version = template['version']
        nbits = template['bits']
        ntime = template['curtime']
        clean_jobs = True
        
        job = {
            'job_id': job_id,
            'prevhash': prevhash,
            'coinbase1': coinbase1,
            'coinbase2': coinbase2,
            'merkle_branches': merkle_branches,
            'version': version,
            'nbits': nbits,
            'ntime': ntime,
            'clean_jobs': clean_jobs,
            'template': template,  # 元のテンプレートを保存
            'pool_difficulty': self.config.getint('STRATUM', 'difficulty', fallback=1)
        }
        
        return job

    def to_little_endian_hex(self, hex_string, byte_length):
        """16進数文字列をリトルエンディアン形式に変換"""
        # 16進数文字列をバイト配列に変換
        if isinstance(hex_string, str):
            # プレフィックス '0x' がある場合は削除
            if hex_string.startswith('0x'):
                hex_string = hex_string[2:]
            
            # 必要に応じてゼロパディング
            hex_string = hex_string.zfill(byte_length * 2)
            
            # バイト配列に変換してリトルエンディアンに
            bytes_data = bytes.fromhex(hex_string)
        else:
            # 整数の場合
            bytes_data = hex_string.to_bytes(byte_length, byteorder='big')
        
        # リトルエンディアンに変換して16進数文字列で返す
        return bytes_data[::-1].hex()

    def calculate_merkle_branches(self, transactions: List[Dict]) -> List[str]:
        """マークルブランチの正確な計算 - 修正版"""
        # トランザクションがない場合は空のリストを返す
        if not transactions:
            return []
        
        # トランザクションハッシュのリスト（リトルエンディアン形式）
        tx_hashes = []
        for tx in transactions:
            # txidはビッグエンディアンなので、リトルエンディアンに変換
            txid_bytes = bytes.fromhex(tx['txid'])
            txid_le = txid_bytes[::-1]  # リトルエンディアンに変換
            tx_hashes.append(txid_le)
        
        # コインベースからマークルルートまでの必要なブランチのみを計算
        branches = []
        index = 0  # コインベースのインデックス
        
        # マークルツリーを構築
        level = tx_hashes.copy()
        
        while len(level) > 1:
            # 奇数個の場合は最後の要素を複製
            if len(level) % 2 != 0:
                level.append(level[-1])
            
            # コインベースパスに必要なブランチのみを追加
            if index % 2 == 0 and index + 1 < len(level):
                # 右の兄弟ノードをブランチに追加（ビッグエンディアンで）
                branches.append(level[index + 1][::-1].hex())
            elif index % 2 == 1 and index - 1 >= 0:
                # 左の兄弟ノードをブランチに追加（ビッグエンディアンで）
                branches.append(level[index - 1][::-1].hex())
        
            # 次のレベルでのハッシュを計算
            next_level = []
            for i in range(0, len(level), 2):
                # ハッシュを正しい順序で連結してdouble SHA-256
                hash1_bytes = level[i]
                hash2_bytes = level[i + 1] if i + 1 < len(level) else level[i]
                
                # 連結してdouble SHA-256（結果は既にリトルエンディアン）
                combined_hash = self.double_sha256(hash1_bytes + hash2_bytes)
                next_level.append(combined_hash)
        
            # 次のレベルでのインデックスを計算
            index = index // 2
            level = next_level
    
        return branches

    def add_miner(self, miner_id: str, connection: Any):
        """マイナーをプールに追加"""
        if (miner_id not in self.miners):
            self.miners[miner_id] = {
                'shares': 0,
                'connection': connection,
                'last_active': time.time()
            }
            self.logger.info(f'Miner {miner_id} added.')
            
            # 現在のジョブがあれば即座に送信
            if self.jobs:
                self.send_job_to_miner(miner_id, self.jobs[-1])
        else:
            # 既存のマイナーであれば接続を更新
            self.miners[miner_id]['connection'] = connection
            self.miners[miner_id]['last_active'] = time.time()
            self.logger.info(f'Miner {miner_id} reconnected.')

    def remove_miner(self, miner_id: str):
        """マイナーをプールから削除"""
        if miner_id in self.miners:
            del self.miners[miner_id]
            self.logger.info(f'Miner {miner_id} removed.')

    def distribute_job(self, job: Dict):
        """全マイナーにジョブを配布"""
        self.jobs.append(job)
        
        # 古いジョブの削除 - より多くのジョブを保持する (5→20)
        if len(self.jobs) > 20:  # 最大20個のジョブを保持
            self.jobs = self.jobs[-20:]
        
        for miner_id in self.miners:
            self.send_job_to_miner(miner_id, job)

    def send_job_to_miner(self, miner_id: str, job: Dict):
        """マイナーにジョブを送信"""
        if miner_id in self.miners and 'connection' in self.miners[miner_id]:
            try:
                connection = self.miners[miner_id]['connection']
                # Stratumプロトコルに従ってジョブ通知を作成
                notify_params = [
                    job['job_id'],
                    job['prevhash'],
                    job['coinbase1'],
                    job['coinbase2'],
                    job['merkle_branches'],
                    job['version'],
                    job['nbits'],
                    job['ntime'],
                    job['clean_jobs']
                ]
                
                notify_message = {
                    "id": None,
                    "method": "mining.notify",
                    "params": notify_params
                }
                
                # 非同期送信（実際の実装はStratumServerクラスに依存）
                asyncio.create_task(connection.send_message(json.dumps(notify_message)))
                self.logger.debug(f'Job sent to miner {miner_id}')
            except Exception as e:
                self.logger.error(f'Error sending job to miner {miner_id}: {e}')
        else:
            self.logger.warning(f'Cannot send job to miner {miner_id}: Not connected')

    def submit_share(self, miner_id: str, job_id: int, extranonce2: str, ntime: str, nonce: str) -> tuple[bool, str]:
        """マイナーからのシェア提出を処理"""
        if miner_id not in self.miners:
            return False, "Unknown miner"
            
        # ジョブの検証
        job = None
        for j in self.jobs:
            if j['job_id'] == job_id:
                job = j
                break
                
        if not job:
            return False, "Job not found"
            
        # シェアの検証（実際にはここでハッシュ計算と難易度チェックを行う）
        # 本来はより複雑な検証が必要
        
        # シェアをカウント
        self.miners[miner_id]['shares'] += 1
        self.miners[miner_id]['last_active'] = time.time()
        
        self.logger.info(f'Share accepted from miner {miner_id}, total: {self.miners[miner_id]["shares"]}')
        
        # 標準ブロック難易度を満たすかチェック
        is_block = self.check_if_block(job, extranonce2, ntime, nonce)
        if is_block:
            # ブロックを提出
            block_hex = self.assemble_block(job, extranonce2, ntime, nonce)
            response = self.bitcoin_rpc.submit_block(block_hex)
            
            if 'error' not in response or response['error'] is None:
                self.logger.info(f"Block submitted successfully by miner {miner_id}!")
            else:
                self.logger.warning(f"Block submission failed: {response['error']}")
        
        return True, "Share accepted"

    def check_if_block(self, job: Dict, extranonce2: str, ntime: str, nonce: str) -> bool:
        """シェアがブロックの要件を満たしているか検証"""
        # この簡易実装は削除し、validate_shareに統合
        # 実際の検証は validate_share メソッドで行う
        header_hash_int, target = self.calculate_hash(job, extranonce2, ntime, nonce)
        return header_hash_int <= target

    def assemble_block(self, job: Dict, extranonce2: str, ntime: str, nonce: str) -> str:
        """ブロックを組み立て、16進数形式で返す"""
        return "assembled_block_hex_here"

    async def validate_share(self, worker_name, bitcoin_address, job_id, extranonce1, extranonce2, ntime, nonce, version, version_mask=None, difficulty=None):
        """ckpool-soloと同じ方式でシェア検証"""
        try:
            # デバッグ情報を最初に出力
            print(f"validate_share called with:")
            print(f"  worker_name: {worker_name}")
            print(f"  bitcoin_address: {bitcoin_address}")
            print(f"  job_id: {job_id}")
            print(f"  extranonce1: {extranonce1}")
            print(f"  extranonce2: {extranonce2}")
            print(f"  ntime: {ntime}")
            print(f"  nonce: {nonce}")
            print(f"  version: {version}")
            
            # デバッグログの追加
            print(f"Validating share - Job ID: {job_id}, Worker: {worker_name}")
            
            # 16進数文字列から整数に変換
            try:
                numeric_job_id = int(job_id, 16)
            except ValueError:
                print(f"Invalid job_id format: {job_id}")
                return {'valid': False, 'reason': 'Invalid job ID format'}
            
            # ジョブの存在確認
            job = None
            for j in self.jobs:
                if j['job_id'] == numeric_job_id:
                    job = j
                    break
                    
            if not job:
                print(f"Job not found for ID: {job_id}")
                return {'valid': False, 'reason': 'Job not found'}
            
            # 2. 不正確なタイミングをチェック
            job_ntime = int(job['ntime'], 16) if isinstance(job['ntime'], str) else job['ntime']
            submit_ntime = int(ntime, 16)

            if abs(job_ntime - submit_ntime) > 600:
                return {'valid': False, 'reason': 'Time out of range'}
            
            # 3. 重複提出チェック
            share_key = f"{worker_name}:{job_id}:{extranonce2}:{ntime}:{nonce}"
            if share_key in self.submitted_shares:
                return {'valid': False, 'reason': 'Duplicate share'}
            
            self.submitted_shares[share_key] = time.time()
            
            try:
                # 4. コインベーストランザクションの構築
                coinbase_tx = job['coinbase1'] + extranonce1 + extranonce2 + job['coinbase2']
                coinbase_hash = self.double_sha256(bytes.fromhex(coinbase_tx))
                
                # 5. マークルルートの計算
                # 標準的なビットコインの実装: double_sha256(coinbase + branch)
                merkle_root = coinbase_hash
                
                for branch in job['merkle_branches']:
                    # ブランチはStratumプロトコルではビッグエンディアンの16進数文字列
                    # これをバイト列に変換（そのまま使用）
                    branch_bytes = bytes.fromhex(branch)
                    
                    # double_sha256(merkle_root + branch_bytes)
                    merkle_root = self.double_sha256(merkle_root + branch_bytes)
                
                # ckpool-solo specific: Flip 32-bit words of the Merkle Root
                def flip_bytes(data):
                    return b"".join([data[i:i+4][::-1] for i in range(0, len(data), 4)])

                merkle_root_flipped = flip_bytes(merkle_root)
                
                # 6. ブロックヘッダーの構築 (ckpool style: Big Endian components, then flip80)
                
                # バージョン (Version Rolling logic: OR the client bits with job version)
                job_version_int = job.get('version', 0x20000000)
                if version:
                    # version is the mask/bits sent by client (hex string)
                    # ckpool logic: *data32 |= version_mask (where data32 is job version)
                    client_version_int = int(version, 16)
                    final_version_int = job_version_int | client_version_int
                    version_bytes = final_version_int.to_bytes(4, 'big')
                    print(f"Version rolling: Job=0x{job_version_int:08x}, Client={version}, Final=0x{final_version_int:08x}")
                else:
                    version_bytes = job_version_int.to_bytes(4, 'big')

                if len(version_bytes) != 4:
                    version_bytes = version_bytes.ljust(4, b'\x00')

                # 前ブロックハッシュ
                prevhash_bytes = bytes.fromhex(job['prevhash'])
                
                # ntime
                ntime_bytes = bytes.fromhex(ntime)
                if len(ntime_bytes) != 4:
                    ntime_bytes = ntime_bytes.ljust(4, b'\x00')

                # nbits
                nbits_bytes = bytes.fromhex(job['nbits'])
                if len(nbits_bytes) != 4:
                    nbits_bytes = nbits_bytes.ljust(4, b'\x00')

                # nonce
                nonce_bytes = bytes.fromhex(nonce)
                if len(nonce_bytes) != 4:
                    nonce_bytes = nonce_bytes.ljust(4, b'\x00')

                # Construct header with FLIPPED merkle root and BE components
                block_header_be = version_bytes + prevhash_bytes + merkle_root_flipped + ntime_bytes + nbits_bytes + nonce_bytes
                
                # Flip the entire 80-byte header
                block_header_flipped = flip_bytes(block_header_be)
                
                # 7. ハッシュ計算
                header_hash = self.double_sha256(block_header_flipped)

                # For block submission, we need the standard header (Little Endian, no flips)
                # merkle_root is already LE. Others are BE and need reversing.
                block_header = version_bytes[::-1] + prevhash_bytes[::-1] + merkle_root + ntime_bytes[::-1] + nbits_bytes[::-1] + nonce_bytes[::-1]
                
                # 8. プール難易度による検証
                # ハッシュ値をリトルエンディアンの整数として解釈
                header_hash_int = int.from_bytes(header_hash, byteorder='little')
                
                # Use provided difficulty or fallback to job difficulty
                current_difficulty = difficulty if difficulty is not None else job['pool_difficulty']
                pool_target = self.difficulty_to_target(current_difficulty)
                share_valid = header_hash_int <= pool_target

                print(f"Share validation details (ckpool-solo flipped):")
                print(f"  Pool difficulty: {current_difficulty}")
                print(f"  Pool target: 0x{pool_target:064x}")
                print(f"  Hash (LE bytes): {header_hash.hex()}")
                print(f"  Hash (BE hex):   {header_hash[::-1].hex()}")
                print(f"  Hash int (LE):   0x{header_hash_int:064x}")
                print(f"  Valid: {share_valid}")
                
                # 9. ネットワーク難易度による検証
                network_target = self.bits_to_target(job['nbits'])
                block_found = header_hash_int <= network_target
                
                if share_valid:
                    self.record_share(worker_name, bitcoin_address, current_difficulty, block_found)
                    
                    if block_found:
                        await self.submit_block(block_header, job, bitcoin_address, worker_name)
                    
                    return {
                        'valid': True,
                        'block_found': block_found,
                        'hash': header_hash.hex()
                    }
                else:
                    return {'valid': False, 'reason': 'Share above target'}
                
            except Exception as e:
                self.logger.error(f"Error validating share: {e}")
                import traceback
                traceback.print_exc()
                return {'valid': False, 'reason': f'Validation error: {str(e)}'}
        except Exception as e:
            self.logger.error(f"Error validating share: {e}")
            return {'valid': False, 'reason': f'Validation error: {str(e)}'}

    def double_sha256(self, data):
        """データのdouble SHA-256ハッシュを計算（ビットコイン標準）"""
        import hashlib
        return hashlib.sha256(hashlib.sha256(data).digest()).digest()

    def test_hash_calculation(self):
        """ハッシュ計算のテスト用メソッド"""
        # 既知のテストケース（genesis block）
        test_header = "0100000000000000000000000000000000000000000000000000000000000000000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a29ab5f49ffff001d1dac2b7c"
        test_bytes = bytes.fromhex(test_header)
        test_hash = self.double_sha256(test_bytes)
        expected_hash = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
        
        # シンプル逆転のみテスト
        simple_reverse = test_hash[::-1].hex()
        
        print(f"Test hash calculation:")
        print(f"  Input: {test_header}")
        print(f"  Output (LE): {test_hash.hex()}")
        print(f"  Simple reverse: {simple_reverse}")
        print(f"  Expected:       {expected_hash}")
        print(f"  Match: {simple_reverse == expected_hash}")
        
        return simple_reverse == expected_hash

    def difficulty_to_target(self, difficulty):
        """難易度からターゲット値を正確に計算 (ckpool-solo互換)"""
        if difficulty <= 0.0:
            return 2**256 - 1  # 最大ターゲット値
    
        # ckpool-soloと同じ標準的なBitcoin難易度1ターゲット (0x1d00ffff)
        # これはBitcoin Genesisブロックで使用された基準値
        bits_value = 0x1d00ffff
        mantissa = bits_value & 0x00ffffff  # 0x00ffff
        exponent = (bits_value >> 24) & 0xff  # 0x1d = 29
        max_target = mantissa * (2 ** (8 * (exponent - 3)))
        
        try:
            target_value = int(max_target / difficulty)
            
            # ターゲット値が最大値を超えないようにチェック
            if target_value > max_target:
                target_value = max_target
                
            # デバッグ情報
            print(f"Difficulty: {difficulty}")
            print(f"Bits value: 0x{bits_value:08x} (ckpool-solo standard)")
            print(f"Mantissa: 0x{mantissa:06x}")
            print(f"Exponent: {exponent}")
            print(f"Max target: 0x{max_target:064x}")
            print(f"Calculated target: 0x{target_value:064x}")
            print(f"Target bit length: {target_value.bit_length()} bits")
            
            return target_value
            
        except (ZeroDivisionError, OverflowError) as e:
            print(f"Error calculating target: {e}")
            return max_target
            
        except (ZeroDivisionError, OverflowError) as e:
            print(f"Error calculating target: {e}")
            return max_target

    def bits_to_target(self, bits_hex):
        """bitsフィールドからターゲット値を計算"""
        bits = int(bits_hex, 16)
        exponent = ((bits >> 24) & 0xff)
        mantissa = bits & 0x00ffffff
        return mantissa * (2 ** (8 * (exponent - 3)))

    def record_share(self, worker_name, bitcoin_address, difficulty, block_found=False):
        """シェア統計を記録"""
        now = time.time()
        
        # ワーカー統計の更新
        if worker_name not in self.worker_stats:
            self.worker_stats[worker_name] = {
                'shares': 0,
                'rejected': 0,
                'last_share': now,
                'blocks_found': 0,
                'bitcoin_address': bitcoin_address  # 支払いアドレスを記録
            }
        
        self.worker_stats[worker_name]['shares'] += 1
        self.worker_stats[worker_name]['last_share'] = now
        
        if block_found:
            self.worker_stats[worker_name]['blocks_found'] += 1
            self.blocks_found += 1
            self.logger.info(f"Block found by {worker_name} (Address: {bitcoin_address})!")

    async def submit_block(self, header_bytes, job, bitcoin_address, worker_name=None):
        # worker_name が None の場合、bitcoin_address を使用
        if worker_name is None:
            worker_name = bitcoin_address
        
        # 以下、既存のコード...
        try:
            # コインベーストランザクション + その他のトランザクションでブロックを構築
            block = {
                'header': header_bytes.hex(),
                'transactions': job['transactions']
            }
            
            # Bitcoin RPCを使用してブロックを提出
            result = await self.bitcoin_rpc.submitblock(block)
            self.logger.info(f"Block submission result: {result}")
            
            # ブロック提出履歴を記録
            block_hash = self.double_sha256(header_bytes)[::-1].hex()
            height = job.get('height', 'unknown')
            
            # 報酬計算
            reward = job['template']['coinbasevalue'] / 100000000.0  # satoshi to BTC
            
            self.submitted_blocks.append({
                'timestamp': time.time(),
                'hash': block_hash,
                'height': height,
                'result': result,
                'finder': worker_name,
                'bitcoin_address': bitcoin_address
            })
            
            return result
        except Exception as e:
            self.logger.error(f"Error submitting block: {e}")
            return f"Error: {str(e)}"


    async def get_current_job(self):
        """現在のジョブを返す。なければ新しいジョブを作成"""
        # 現在のジョブがなければ更新を試みる
        if not self.jobs or len(self.jobs) == 0:
            await self.update_block_template()
        
        # 最新のジョブを返す
        if self.jobs and len(self.jobs) > 0:
            return self.jobs[-1]
        
        # ジョブがない場合はNoneを返す
        return None

    def create_coinbase_tx(self, height, block_reward, address):
        """C言語の実装を参考にした堅牢なコインベーストランザクション生成"""
        import time
        import struct
        import binascii
        
        # scriptsig_header_bin の Python 相当
        scriptsig_header = bytes.fromhex(
            "01000000" +                  # version
            "01" +                        # tx_in count
            "0000000000000000000000000000000000000000000000000000000000000000" +  # prev hash
            "ffffffff" +                  # prev index
            "00"                          # script_sig length (placeholder)
        )
        
        # VarInt エンコード関数
        def encode_varint(n):
            if n < 0xfd:
                return bytes([n])
            elif n <= 0xffff:
                return b'\xfd' + struct.pack("<H", n)
            elif n <= 0xffffffff:
                return b'\xfe' + struct.pack("<I", n)
            else:
                return b'\xff' + struct.pack("<Q", n)
        
        # 整数をVarIntとして直列化
        def ser_number(n):
            if n < 0x01:
                return bytes([n])
            elif n <= 0xff:
                return bytes([0x01, n])
            elif n <= 0xffff:
                return bytes([0x02]) + struct.pack("<H", n)
            elif n <= 0xffffffff:
                return bytes([0x03]) + struct.pack("<I", n)
            elif n <= 0xffffffffffffffff:
                return bytes([0x04]) + struct.pack("<Q", n)
            else:
                return bytes([0x05]) + struct.pack("<Q", n)
        
        # coinb1bin 生成
        coinb1bin = bytearray(scriptsig_header)
        ofs = len(scriptsig_header)
        
        # スクリプト長プレースホルダのインデックス
        script_len_pos = ofs - 1
        
        # ブロック高さを追加
        height_bytes = ser_number(height)
        coinb1bin.extend(height_bytes)
        ofs += len(height_bytes)
        
        # フラグを追加 (例: "/ckpool/")
        flags = b"Kazumyon Mining Pool"
        coinb1bin.append(len(flags))  # フラグの長さ
        coinb1bin.extend(flags)
        ofs += 1 + len(flags)
        
        # タイムスタンプを追加
        now = int(time.time())
        time_bytes = ser_number(now)
        coinb1bin.extend(time_bytes)
        ofs += len(time_bytes)
        
        # ナノ秒タイムスタンプを追加 (一意のランダマイザ)
        nsec = int((time.time() % 1) * 1000000000)
        nsec_bytes = ser_number(nsec)
        coinb1bin.extend(nsec_bytes)
        ofs += len(nsec_bytes)
        
        # エクストラノンスの長さ
        # 設定から取得するか、固定値を使用
        enonce1varlen = 4  # 例: 4バイト
        enonce2varlen = 4  # 例: 4バイト
        coinb1bin.append(enonce1varlen + enonce2varlen)
        ofs += 1
        
        # coinb1bin の長さを設定
        coinb1len = ofs
        
        # スクリプト長を設定
        script_len = coinb1len - script_len_pos - 1 + enonce1varlen + enonce2varlen - 1
        coinb1bin[script_len_pos] = script_len
        
        # coinb1 完成 (hex文字列に変換)
        coinb1 = binascii.hexlify(coinb1bin).decode('ascii')
        
        # coinb2bin 生成
        coinb2bin = bytearray()
        
        # オプションのシグネチャ
        # ここでは "ckpool" 相当を追加
        pool_sig = b"\x0aKazumyon"
        coinb2bin.extend(pool_sig)
        
        # シーケンス
        coinb2bin.extend(b"\xff\xff\xff\xff")
        
        # 出力数 (VarInt) - 単一出力の場合は 0x01
        coinb2bin.append(0x01)
        
        # 報酬金額 (リトルエンディアン, 8バイト)
        coinb2bin.extend(struct.pack("<Q", block_reward))
        
        # ScriptPubKey を追加
        script_pubkey_hex = self.address_to_script_pubkey(address)
        script_pubkey_bin = bytes.fromhex(script_pubkey_hex)
        
        # ScriptPubKey 長を VarInt として追加
        coinb2bin.extend(encode_varint(len(script_pubkey_bin)))
        
        # ScriptPubKey データを追加
        coinb2bin.extend(script_pubkey_bin)
        
        # ロックタイム (4バイト)
        coinb2bin.extend(b"\x00\x00\x00\x00")
        
        # coinb2 完成 (hex文字列に変換)
        coinb2 = binascii.hexlify(coinb2bin).decode('ascii')
        
        # スクリプト生成の詳細をログに記録
        print(f"Address: {address}")
        print(f"Script PubKey Hex: {script_pubkey_hex}")
        print(f"Coinbase1: {coinb1[:64]}...")
        print(f"Coinbase2: {coinb2[:64]}...")
        
        return {
            "coinbase1": coinb1,
            "coinbase2": coinb2
        }

    # クラス内のメソッドとして address_to_script_pubkey を追加
    def address_to_script_pubkey(self, address):
        """ビットコインアドレスを適切なscriptPubKeyに変換"""
        if address.startswith('tb1'):  # Bech32アドレス（SegWit）
            # 正しい呼び出し - SegWitアドレスのデコード
            hrp = "tb"  # テストネットのHRP (Human Readable Part)
            decoded = self.bech32.bech32_decode(address)
    
            if decoded[0] is not None:
                # データを5ビットから8ビットに変換
                data = self.bech32.convertbits(decoded[1][1:], 5, 8, False)
                # print(f"Decoded HRP: {decoded[0]}, Data: {data}")
        
            if data:
                witness_version = decoded[1][0]
                witness_program = data
                
                if len(witness_program) == 20:  # P2WPKH
                    # 0 <20-byte-key-hash>
                    script_pubkey = '0014' + bytes(witness_program).hex()
                    return script_pubkey
                elif len(witness_program) == 32:  # P2WSH
                    # 0 <32-byte-script-hash>
                    script_pubkey = '0020' + bytes(witness_program).hex()
                    return script_pubkey
        elif address.startswith('2'):  # P2SH
            # P2SH Script: OP_HASH160 <20-byte-hash> OP_EQUAL
            try:
                decode_address = self.base58.b58decode_check(address)[1:]  # remove version byte
                return 'a914' + decode_address.hex() + '87'
            except Exception as e:
                print(f"Error decoding P2SH address: {e}")
                return '6a00'  # デフォルト: 空のスクリプト
        elif address.startswith('m') or address.startswith('n'):  # P2PKH testnet
            # P2PKH Script: OP_DUP OP_HASH160 <20-byte-hash> OP_EQUALVERIFY OP_CHECKSIG
            try:
                decode_address = self.base58.b58decode_check(address)[1:]  # remove version byte
                return '76a914' + decode_address.hex() + '88ac'
            except Exception as e:
                print(f"Error decoding P2PKH address: {e}")
                return '6a00'  # デフォルト: 空のスクリプト
        
        # デフォルト: 空のスクリプト
        return '6a00'  # OP_RETURN 0

    def register_worker(self, client_id, worker_name):
        """ワーカーを登録する"""
        if not hasattr(self, 'miners'):
            self.miners = {}

        if client_id not in self.miners:
            self.miners[client_id] = {
                'worker_name': worker_name,
                'bitcoin_address': worker_name,  # アドレスとワーカー名が同じと仮定
                'shares': 0,
                'last_active': time.time()
            }
            self.logger.info(f"Worker registered: {worker_name} (client: {client_id})")
        else:
            self.miners[client_id]['worker_name'] = worker_name
            self.miners[client_id]['bitcoin_address'] = worker_name
            self.miners[client_id]['last_active'] = time.time()
            self.logger.info(f"Worker updated: {worker_name} (client: {client_id})")