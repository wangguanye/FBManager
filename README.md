# FBManager - Facebook 账号管理与自动化养号系统

FBManager 是一个基于 Python FastAPI 和 Playwright 的 Facebook 账号管理系统，旨在提供账号管理、代理管理、RPA 自动化养号、任务调度等一站式解决方案。

## 最新更新

- **2026-03-09**: 优化代码同步流程，新增自动化 Git 脚本。


-   **账号管理**：集中管理 Facebook 账号信息（账号、密码、2FA、Cookie 等）。
-   **代理管理**：支持 HTTP/SOCKS5 代理，自动关联账号。
-   **自动化养号 (RPA)**：
    -   基于 Playwright 和比特浏览器（BitBrowser）。
    -   支持自动刷 Feed、点赞、观看 Reels、检查账号状态等。
    -   可配置的 SOP（标准作业程序）策略。
-   **任务调度**：
    -   基于 APScheduler 的任务调度。
    -   支持每日自动生成养号任务。
    -   并发控制和静默期设置。
-   **监控与告警**：
    -   实时监控任务执行状态。
    -   Dashboard 可视化展示。
    -   系统日志与异常告警。
-   **系统维护**：
    -   自动/手动数据库备份。
    -   自动清理过期日志。

## 环境要求

-   **操作系统**: Windows (推荐) / Linux / macOS
-   **Python**: 3.11+
-   **浏览器环境**: [比特浏览器 (BitBrowser)](https://www.bitbrowser.cn/) (必须安装并运行，用于指纹浏览器环境)
-   **数据库**: SQLite (内置)

## 安装步骤

1.  **克隆项目**
    ```bash
    git clone https://github.com/your-repo/FBManager.git
    cd FBManager
    ```

2.  **创建虚拟环境 (推荐)**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Linux/macOS
    source venv/bin/activate
    ```

3.  **安装依赖**
    ```bash
    pip install -r requirements.txt
    ```
    *如果没有 `requirements.txt`，请安装核心依赖：*
    ```bash
    pip install fastapi uvicorn[standard] sqlalchemy aiosqlite jinja2 pyyaml loguru httpx apscheduler cryptography playwright
    ```

4.  **安装 Playwright 浏览器驱动**
    ```bash
    playwright install chromium
    ```

## 快速开始

1.  **配置比特浏览器**
    -   启动比特浏览器。
    -   确保 RPA 端口配置为 `54345` (默认) 或修改 `modules/rpa/browser_client.py` 中的配置。

2.  **启动应用**
    ```bash
    uvicorn main:app --reload --port 8000
    ```
    -   首次启动时，系统会自动：
        -   初始化 SQLite 数据库 `fb_manager.db`。
        -   生成加密密钥并保存到 `.env` 文件（请妥善保管）。
        -   执行一次数据库备份。

3.  **访问仪表盘**
    -   打开浏览器访问: [http://127.0.0.1:8000](http://127.0.0.1:8000)

## 配置文件说明 (`config.yaml`)

主要配置项如下：

```yaml
# 调度器配置
scheduler:
  max_concurrent_windows: 5  # 最大并发窗口数
  account_interval_min: 5    # 账号操作最小间隔（分钟）
  silent_hours_start: 2      # 静默期开始（凌晨2点）
  silent_hours_end: 5        # 静默期结束（凌晨5点）

# RPA 配置
rpa:
  action_delay_min: 2        # 动作最小延迟（秒）
  action_delay_max: 8        # 动作最大延迟（秒）

# 数据备份与日志保留
backup:
  max_backups: 30            # 保留最近30份备份
  backup_dir: "backups/"     # 备份目录

log_retention:
  info_days: 30              # INFO日志保留30天
  warn_error_days: 90        # 错误日志保留90天
```

## 数据备份与恢复

-   **自动备份**: 每次系统启动时会自动备份数据库到 `backups/` 目录。
-   **手动备份**: 在 Dashboard 首页点击 "💾 立即备份" 按钮。
-   **恢复数据**:
    1.  停止服务 (Ctrl+C)。
    2.  将 `backups/` 目录下指定的备份文件（如 `fbmanager_20240309_120000.db`）复制到项目根目录。
    3.  重命名为 `fbmanager.db`（建议先备份当前的 `fbmanager.db`）。
    4.  重启服务。

## 目录结构

```
FBManager/
├── main.py                 # 入口文件
├── config.yaml             # 配置文件
├── fbmanager.db            # SQLite 数据库
├── fernet.key              # 加密密钥
├── backups/                # 数据库备份目录
├── modules/                # 业务模块
│   ├── asset/              # 资产管理 (账号/代理)
│   ├── monitor/            # 监控与日志
│   ├── nurture/            # 养号逻辑
│   ├── rpa/                # RPA 执行引擎
│   └── system/             # 系统维护 (备份/清理)
├── core/                   # 核心组件 (调度器)
├── db/                     # 数据库连接
├── templates/              # 前端模板
└── static/                 # 静态资源
```

## 常见问题

-   **RPA 无法启动**: 请检查比特浏览器是否开启，并且端口是否为 `54345`。
-   **任务未生成**: 检查账号状态是否为 "养号中"，以及 `config.yaml` 中 SOP 配置是否正确。
