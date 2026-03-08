import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv, set_key

# 加载 .env 文件
load_dotenv()

def get_fernet_key() -> str:
    """
    获取 Fernet 密钥。如果 .env 中不存在，则生成一个新的并保存。
    """
    key = os.getenv("FERNET_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        # 自动创建 .env 文件或在其中设置密钥
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if not os.path.exists(env_path):
            with open(env_path, "w") as f:
                f.write(f"FERNET_KEY={key}\n")
        else:
            set_key(env_path, "FERNET_KEY", key)
        # 更新环境变量以便后续调用
        os.environ["FERNET_KEY"] = key
    return key

# 初始化 Fernet
FERNET_KEY = get_fernet_key()
fernet = Fernet(FERNET_KEY.encode())

def encrypt_value(value: str) -> str:
    """
    使用 Fernet 加密字符串。
    """
    if not value:
        return value
    return fernet.encrypt(value.encode()).decode()

def decrypt_value(encrypted_value: str) -> str:
    """
    使用 Fernet 解密字符串。
    """
    if not encrypted_value:
        return encrypted_value
    return fernet.decrypt(encrypted_value.encode()).decode()
