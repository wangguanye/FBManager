
import subprocess
import sys
import os

def log_info(message):
    print(f"\033[92m[INFO] {message}\033[0m")

def log_error(message):
    print(f"\033[91m[ERROR] {message}\033[0m")

def log_warning(message):
    print(f"\033[93m[WARNING] {message}\033[0m")

def run_command(command, check=True):
    try:
        result = subprocess.run(
            command,
            check=check,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'  # 显式指定 UTF-8
        )
        return result
    except subprocess.CalledProcessError as e:
        raise e

def check_git_status():
    result = run_command("git status --porcelain")
    if result.stdout.strip():
        log_info("检测到未提交的更改，正在自动添加并提交...")
        run_command("git add .")
        run_command('git commit -m "auto: sync local changes"')
    else:
        log_info("工作区干净，无未提交更改。")

def sync_code():
    try:
        log_info("正在拉取远程更新 (git pull --rebase)...")
        # 使用 rebase 避免产生不必要的合并提交
        run_command("git pull --rebase origin main")
        
        log_info("正在推送到远程仓库 (git push)...")
        run_command("git push origin main")
        
        log_info("同步成功！")
    except subprocess.CalledProcessError as e:
        log_error("同步过程中发生错误。")
        error_msg = e.stderr
        log_error(error_msg)
        
        if "conflict" in error_msg.lower():
            log_error("检测到代码冲突，请手动解决冲突后再次运行此脚本。")
        elif "time out" in error_msg.lower() or "could not resolve host" in error_msg.lower():
            log_error("网络连接问题。如果您使用了代理，请配置 Git 代理：")
            log_error("git config --global http.proxy http://127.0.0.1:7890")
            log_error("（请将 7890 替换为您的代理端口）")
        elif "permission denied" in error_msg.lower() or "authentication failed" in error_msg.lower():
            log_error("认证失败。请检查您的 GitHub 凭证。")
            
        sys.exit(1)

def main():
    print("\033[96m=== 开始代码同步 ===\033[0m")
    
    # 检查 OneDrive
    cwd = os.getcwd()
    if "OneDrive" in cwd:
        log_warning("检测到项目位于 OneDrive 目录下。OneDrive 的同步可能会锁定文件导致 Git 操作失败。")
        log_warning("建议暂停 OneDrive 同步，或将项目移动到非 OneDrive 目录。")

    try:
        check_git_status()
        sync_code()
    except Exception as e:
        log_error(f"发生未知错误: {str(e)}")
        sys.exit(1)

    print("\033[96m=== 同步完成 ===\033[0m")

if __name__ == "__main__":
    main()
