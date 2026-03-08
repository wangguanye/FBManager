# FBManager

Facebook 账号管理与自动化养号系统。

## 项目结构

- `main.py`: FastAPI 入口
- `config.yaml`: 业务配置
- `.env`: 敏感配置
- `core/`: 核心逻辑（加密、调度、状态级联）
- `modules/`: 业务模块（资产管理、养号、RPA、广告、监控）
- `db/`: 数据库配置与模型
- `templates/`: Jinja2 模板
- `static/`: 静态资源

## 快速开始

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

2. 运行应用：
   ```bash
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```

## 配置说明

- 业务配置请修改 `config.yaml`。
- 敏感信息（如加密密钥）存储在 `.env` 中。
