# ADR-0016: Alembic 数据库迁移框架初始化

**日期**: 2026-06-13
**状态**: 已接受
**决策者**: DevOps

---

## 背景

ShortURL 项目目前使用 `Base.metadata.create_all()` 在应用启动时自动创建数据库表。这种方式在开发阶段快速方便，但存在以下生产环境风险：

1. **不可逆变更**：无版本控制，无法回滚 schema 变更
2. **无审核机制**：schema 变更无法代码审查，直接通过代码修改生效
3. **多环境不同步**：开发/测试/生产环境的 schema 状态难以保证一致
4. **协作冲突**：多人同时修改模型时，无法通过迁移版本解决冲突

项目已使用 SQLAlchemy 2.0+ ORM，PostgreSQL 支持已配置（database.py 含 pool_pre_ping、连接池等），具备迁移框架接入条件。

## 决策

**引入 Alembic 作为数据库迁移管理工具。**

### 工具选择

| 维度 | Alembic | 替代方案比较 |
|------|---------|-------------|
| SQLAlchemy 原生 | 官方维护，与 ORM 深度集成 | 无更好替代 |
| 自动生成 | `--autogenerate` 自动对比模型生成迁移 | 减少手工编写工作量 |
| 双数据库 | 同时支持 SQLite 和 PostgreSQL 方言 | 关键需求 |
| CI/CD 集成 | 可嵌入 CI 流程验证迁移 | 满足生产需求 |

### 配置方案

#### 目录结构

```
shorturl/
  alembic.ini                  # Alembic 全局配置（脚本路径、日志级别）
  migrations/
    env.py                     # 运行环境配置（数据库连接、目标元数据）
    script.py.mako             # 迁移文件模板
    versions/                  # 迁移版本文件目录
      9f415b8b77b4_initial_schema.py  # 初始迁移
```

#### 数据库 URL 策略

- `alembic.ini` 中的 `sqlalchemy.url` 仅用作后备默认值（SQLite 本地开发）
- 运行时 `migrations/env.py` 通过 `get_url()` 从 `app.config.Config.database_url` 获取真实 URL
- 生产环境通过 `DATABASE_URL` 环境变量配置 PostgreSQL 连接
- 未设置环境变量时默认使用 `sqlite:///./shorturl.db`

```python
# migrations/env.py 核心逻辑
from app.config import config as app_config
from app.models.link import Base

target_metadata = Base.metadata

def get_url() -> str:
    return app_config.database_url  # 优先读取 DATABASE_URL 环境变量
```

#### 自动生成支持

`env.py` 导入了 `app.models.link.Base` 作为 `target_metadata`，支持 `--autogenerate` 自动检测模型变更并生成迁移脚本。

### 阻断策略一致性

Trivy CRITICAL 扫描与 Alembic 迁移均采用**硬阻断**策略：迁移测试失败或 CRITICAL 漏洞发现都会阻止 PR 合并。

## 迁移文件格式

```python
"""迁移描述

Revision ID: abc123
Revises: 
Create Date: 2026-06-13 14:00:40.755939
"""
from alembic import op
import sqlalchemy as sa

revision = 'abc123'
down_revision = None  # 初始迁移无父版本

def upgrade() -> None:
    op.create_table(...)

def downgrade() -> None:
    op.drop_table(...)
```

## 已知限制

1. **SQLite 不支持 ALTER COLUMN**：大多数列类型变更在 SQLite 上无法通过 ALTER TABLE 完成，需使用批次迁移模式（batch mode）。PostgreSQL 无此限制。
2. **SQLite 时间函数差异**：`func.now()` 在 SQLite 生成 `CURRENT_TIMESTAMP`，在 PostgreSQL 生成 `NOW()`。迁移文件会自动适配方言。
3. **自动生成需谨慎**：`--autogenerate` 生成的迁移仍需人工审查，特别是索引、约束和默认值变更。

## 使用方式

```bash
# 升级到最新版本
alembic upgrade head

# 回滚一个版本
alembic downgrade -1

# 自动生成新迁移
alembic revision --autogenerate -m "description"

# 查看当前版本
alembic current

# 查看历史
alembic history
```

## 验证结果

- 初始迁移版本：`9f415b8b77b4`（`initial schema` 迁移）
- 升级验证：`alembic upgrade head` → 成功创建 `links` 表 + `alembic_version` 表
- 回滚验证：`alembic downgrade -1` → 成功删除 `links` 表
- 回滚后再次升级验证：`alembic upgrade head` → 成功恢复 `links` 表
- 数据库：SQLite（开发环境）

## 相关文档

- [ADR-0014: 测试升级 — 属性测试 + 时间Mock + PostgreSQL集成测试](ADR-0014-batch5-test-upgrade.md)
- [SQLAlchemy 2.0 Migrations](https://docs.sqlalchemy.org/en/20/core/metadata.html)
- [Alembic Documentation](https://alembic.sqlalchemy.org/en/latest/)
