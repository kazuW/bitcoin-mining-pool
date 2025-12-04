import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def setup_logging(log_dir="logs", log_level=logging.INFO):
    """ロギングを設定する"""
    os.makedirs(log_dir, exist_ok=True)
    
    # ルートロガーの設定
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # フォーマッタ
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # ファイルハンドラ (ローテーション付き)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'pool.log'), 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    
    # コンソールハンドラ
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # ハンドラをロガーに追加
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def get_logger(name):
    """名前付きロガーを取得する"""
    return logging.getLogger(name)