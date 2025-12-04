from typing import Any, Dict
import json
import aiohttp
import asyncio
import requests

class BitcoinRPC:
    def __init__(self, rpc_user: str, rpc_password: str, rpc_host: str = 'localhost', rpc_port: int = 8332):
        self.rpc_user = rpc_user
        self.rpc_password = rpc_password
        self.rpc_host = rpc_host
        self.rpc_port = rpc_port
        self.headers = {'content-type': 'application/json'}
        self.url = f'http://{self.rpc_host}:{self.rpc_port}/'
        self.session = None

    def _rpc_request(self, method: str, params: list = None) -> Any:
        """同期的なRPC呼び出し（非推奨、互換性のために維持）"""
        if params is None:
            params = []
        payload = {
            "jsonrpc": "1.0",
            "id": "curltest",
            "method": method,
            "params": params,
        }
        response = requests.post(self.url, data=json.dumps(payload), headers=self.headers, auth=(self.rpc_user, self.rpc_password))
        return response.json()

    async def _init_session(self):
        """HTTP セッションを初期化"""
        if self.session is None:
            self.session = aiohttp.ClientSession(auth=aiohttp.BasicAuth(self.rpc_user, self.rpc_password))

    async def call(self, method: str, params: list = None) -> Dict:
        """非同期でRPC呼び出しを実行"""
        if params is None:
            params = []
        
        await self._init_session()
        
        payload = {
            "jsonrpc": "1.0",
            "id": "curltest",
            "method": method,
            "params": params,
        }
        
        async with self.session.post(self.url, json=payload, headers=self.headers) as response:
            return await response.json()

    # 同期メソッド（古い実装、後方互換性のため維持）
    def get_block_template(self, params: list = None) -> Dict:
        return self._rpc_request("getblocktemplate", params)

    def submit_block(self, block_hash: str) -> Dict:
        return self._rpc_request("submitblock", [block_hash])

    # 非同期メソッド（新しい実装）
    async def getblocktemplate(self, params: list = None):
        """ブロックテンプレートを非同期で取得"""
        if params is None:
            params = [{"rules": ["segwit"]}]
        response = await self.call('getblocktemplate', params)
        if 'error' in response and response['error'] is not None:
            raise Exception(f"Failed to get block template: {response['error']}")
        return response['result']

    async def getblockcount(self):
        """現在のブロック高を非同期で取得"""
        response = await self.call('getblockcount')
        if 'error' in response and response['error'] is not None:
            raise Exception(f"Failed to get block count: {response['error']}")
        return response['result']

    async def submitblock(self, block_hex: str):
        """ブロックを非同期で提出"""
        response = await self.call('submitblock', [block_hex])
        if response.get('error'):
            raise Exception(f"Failed to submit block: {response['error']}")
        return response.get('result')

    async def close(self):
        """HTTPセッションを閉じる"""
        if self.session:
            await self.session.close()
            self.session = None