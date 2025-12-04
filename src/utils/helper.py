def sha256_hexdigest(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()

def validate_sha256(expected: str, data: bytes) -> bool:
    return sha256_hexdigest(data) == expected

def format_job_id(job_id: int) -> str:
    return f"{job_id:08x}"  # Format job ID as a zero-padded hexadecimal string

def parse_hex_string(hex_string: str) -> bytes:
    return bytes.fromhex(hex_string)

def format_hex_string(data: bytes) -> str:
    return data.hex()

# 以下の関数を追加
def bytes_to_hex(data: bytes) -> str:
    return data.hex()

def hex_to_bytes(hex_string: str) -> bytes:
    return bytes.fromhex(hex_string)