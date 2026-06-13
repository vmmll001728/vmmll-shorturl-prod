# ShortURL - Alembic Migration & CI Trivy Fix Task Report

## Task 1: Alembic 数据库迁移框架初始化

### 操作步骤
1. **安装 alembic**: `pip install alembic` (v1.18.4)
2. **初始化**: `alembic init migrations` 创建 `migrations/` 目录
3. **配置 `alembic.ini`**: 设置日志级别 WARN, 添加 `version_path_separator = os`
4. **配置 `migrations/env.py`**: 
   - 导入 `app.models.link.Base` 作为 `target_metadata`
   - 通过 `app.config.Config.database_url` 获取数据库URL (支持 DATABASE_URL 环境变量 + SQLite 后备)
   - 支持 offline/online 两种运行模式
   - 手动 logging 配置 (避免 Python 3.12 fileConfig + StreamHandler 兼容问题)
5. **创建初始迁移**: `alembic revision --autogenerate -m "initial schema"`
6. **验证 up/down**: SQLite 上验证成功

### 结果
- **初始迁移版本 SHA**: `9f415b8b77b4`
- **迁移文件**: `migrations/versions/9f415b8b77b4_initial_schema.py`
- **创建表**: `links` (id, alias, original_url, click_count, created_at, expires_at, is_deleted) + `ix_links_alias` 索引
- **升级验证**: `alembic upgrade head` → exit code 0, tables created
- **回滚验证**: `alembic downgrade -1` → exit code 0, `links` table dropped
- **二次升级验证**: exit code 0, tables restored

### 已添加文件
- `alembic.ini` - Alembic 全局配置
- `migrations/env.py` - 运行环境配置
- `migrations/README` - Alembic 自述文件
- `migrations/script.py.mako` - 迁移文件模板
- `migrations/versions/9f415b8b77b4_initial_schema.py` - 初始迁移
- `docs/adr/ADR-0016-alembic-migration-setup.md` - ADR 决策记录
- `requirements.txt` - 新增 `alembic>=1.18.0` 依赖

### 使用方式
```bash
# 开发环境（SQLite，默认）
alembic upgrade head

# 生产环境（PostgreSQL）
DATABASE_URL=postgresql://user:pass@host/dbname alembic upgrade head

# 自动生成新迁移（模型变更后）
alembic revision --autogenerate -m "description"
```

---

## Task 2: CI Trivy 阻断配置修复

### 修改内容

在 `.github/workflows/ci.yml` 的 `container-scan` job 中：

1. **CRITICAL 扫描步骤** (容器镜像 + 文件系统)：
   - 添加 `continue-on-error: false` （显式声明阻止失败传播）
   - 保留 `exit-code: '1'` （发现漏洞时非零退出）
   - 添加注释块 `[BLOCKING]` 说明阻断逻辑

2. **HIGH 扫描步骤** (容器镜像 + 文件系统)：
   - 添加 `continue-on-error: true` （明确不阻断）
   - 保留 `exit-code: '0'` （永不因 HIGH 失败）

3. **Header 注释更新**：
   - `container-scan` 描述从 "仅报告" 改为 "CRITICAL阻断合并，HIGH仅报告"

4. **Summary 阻断策略说明更新**：
   - 详细说明 `continue-on-error: false + exit-code: 1` 的阻断机制

### 阻断逻辑原理
```
CRITICAL step: exit-code=1 + continue-on-error=false
  → 发现 CRITICAL 漏洞 → exit-code=1 → step fails → job fails → PR blocked ✓

HIGH step: exit-code=0 + continue-on-error=true  
  → 发现 HIGH 漏洞 → exit-code=0 → step succeeds → no effect ✓
```

### 注意事项
- job 级别无 `if: always()` 设置，因此 CRITICAL step 失败自然传播到 job 失败
- `summary` job 的 `if: always()` 不受影响，始终执行汇总
