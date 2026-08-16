#!/usr/bin/env python3
"""secrets_env.py — 统一 API 密钥加载（cover-gen.py / summary.py 共用）

加载顺序（发布安全，2026-08-16）：
  1. 环境变量（最高优先）：ZENMUX_API_KEY / DEEPSEEK_API_KEY
  2. 工作区根 `.env` 文件（KEY=VALUE 每行一个，标准库解析，无额外依赖）
  3. （仅本地兜底）$DSH_HOME/.credentials.yaml —— 本仓库旧场景兼容，
     发布版 README 不宣传此路径；找不到密钥时给出明确指引而非硬编码路径

绝不把密钥写入任何仓库文件；.env 已在 .gitignore 排除。
"""

import os
import sys
from pathlib import Path

# 兼容旧场景：脚本从 ReoNa-paper-digest/scripts 运行时，工作区根 = 上上级
WORKSPACE = Path(__file__).resolve().parent.parent.parent


def _load_dotenv() -> dict:
    """解析工作区根 .env（KEY=VALUE，支持 # 注释与引号），不存在则空 dict。"""
    env_path = WORKSPACE / ".env"
    if not env_path.exists():
        return {}
    out = {}
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k:
                out[k] = v
    except OSError:
        pass
    return out


def _load_dsh_credentials() -> dict:
    """旧场景兜底：$DSH_HOME/.credentials.yaml（本仓库历史的 DSH 环境约定）。"""
    dsh = os.environ.get("DSH_HOME", "")
    if not dsh:
        return {}
    cred = Path(dsh) / ".credentials.yaml"
    if not cred.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(cred.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def get_secret(env_name: str, yaml_key: str | None = None) -> str:
    """按 环境变量 → .env → DSH credentials.yaml 顺序取密钥。"""
    val = os.environ.get(env_name, "").strip()
    if val:
        return val
    dotenv = _load_dotenv()
    val = str(dotenv.get(env_name) or "").strip()
    if val:
        return val
    if yaml_key:
        val = str(_load_dsh_credentials().get(yaml_key) or "").strip()
    return val


def require_secret(env_name: str, yaml_key: str | None = None) -> str:
    """取密钥，缺失时给出可操作提示（不硬编码具体路径）。"""
    val = get_secret(env_name, yaml_key)
    if not val:
        print(
            f"[error] 未找到 {env_name}。\n"
            f"  请任选其一：\n"
            f"  1) 设置环境变量：set {env_name}=xxx（PowerShell: $env:{env_name}='xxx'）\n"
            f"  2) 在工作区根创建 .env 文件，写入一行：{env_name}=xxx（.env 已被 gitignore）\n"
            f"  3) 或提供 $DSH_HOME/.credentials.yaml（含 {yaml_key or env_name} 字段）",
            file=sys.stderr,
        )
        sys.exit(1)
    return val
