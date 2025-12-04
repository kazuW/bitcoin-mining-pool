import asyncio
import configparser
import platform
import traceback
import sys
from core.pool import Pool
from core.stratum_server import StratumServer
from utils.logging import setup_logging

# Windows環境の場合はSelectorEventLoopPolicyを使用
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    try:
        # 設定読み込み
        config = configparser.ConfigParser(interpolation=None)  # 文字列補間を無効化
        if not config.read('config/config.ini'):
            raise FileNotFoundError('設定ファイル config/config.ini が見つかりません')
        print("Configuration loaded successfully")

        # プールの初期化
        pool = Pool(config)
        await pool.start()
        
        # Stratumサーバーの初期化
        server = StratumServer(pool, config)
        print("Stratum server initialized successfully")
        
        # シャットダウンハンドラの設定
        try:
            server.setup_signal_handlers()
        except Exception as e:
            print(f"Signal handlers not supported: {e}")
        
        # サーバーの起動
        server_task = asyncio.create_task(server.start())
        
        # ここで完全に停止するのを防ぐためのタスク監視
        try:
            # すべてのタスクが完了するまで待機
            await asyncio.gather(server_task)
        except asyncio.CancelledError:
            print("Main tasks cancelled")
        except Exception as e:
            print(f"Error in main tasks: {e}")
    except FileNotFoundError as e:
        print(f"設定エラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"初期化エラー: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server shutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")