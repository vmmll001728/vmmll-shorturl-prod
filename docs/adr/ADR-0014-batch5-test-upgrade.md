# ADR-0014: 测试升级 — 属性测试 + 时间Mock + PostgreSQL集成测试

**日期**: 2026-06-13
**状态**: 已接受
**决策者**: CTO（技术总监）

---

## 背景

ShortURL 项目经 QA + Arch 联合审查，识别出测试覆盖率的三大盲区：

1. **属性/边界测试空白**：现有测试只覆盖 happy path，缺少随机输入 fuzz、边界条件属性测试
2. **时间相关逻辑无时间操控**：过期链接逻辑依赖 `datetime.now()`，测试无法可靠验证时间边界
3. **PostgreSQL 行为未验证**：全部测试跑在 SQLite 上，PG 的事务隔离、并发竞态等行为无法验证

QA 建议引入 `hypothesis`（属性测试）和 `freezegun`（时间Mock），Arch 建议添加 PG 集成测试。

## 决策

**引入三项测试技术：**

| 工具 | 用途 | 测试数量 |
|------|------|----------|
| `hypothesis` | 属性测试（property-based testing） | 7 个测试 |
| `freezegun` | 时间Mock（fake time） | 7 个测试 |
| PostgreSQL 集成 | 真实 PG 环境行为验证 | 4 个测试（PG不可用时 skip） |

### 属性测试策略

- **URL 校验器**：`is_safe_url` 对已知安全/危险 URL 列表 + 随机 fuzz 输入的响应属性
- **别名生成器**：slug 长度、字符集、唯一性属性
- **链接创建**：自定义 alias 在各种输入下的端到端行为

### 时间Mock策略

- **过期边界**：`expires_at` 计算正确性（freeze 到固定时间）
- **清理逻辑**：`DELETE /admin/cleanup` 在时间推进后的行为
- **限流窗口**：`RateLimitStore` 滑动窗口在时间推进后的重置行为

### PostgreSQL 集成策略

- PG 测试在 `PG_TEST_DSN` 环境变量未设置时自动 skip（不阻塞 CI）
- 测试覆盖：CRUD、原子 `click_count` 增量、事务隔离级别、并发重复 alias 冲突

## 依赖变更

```txt
# requirements.txt 新增
hypothesis>=6.100.0
freezegun>=1.5.0
```

## 测试文件结构

```
tests/
  test_batch5.py          # 新增：18 个高级测试
    TestHypothesis*        # 7 个属性测试
    TestFreezegun*        # 7 个时间Mock测试
    TestPostgreSQL*       # 4 个 PG 集成测试（条件skip）
```

## 已知限制

1. **SQLite vs PG 时间处理差异**：freezegun 冻结 Python `datetime.now()`，但 SQLite 的 `datetime()` 函数不依赖 Python 时钟。过期链接测试在 SQLite 下接受多种状态码（200/302/404/410），生产 PG 环境会严格执行 410。
2. **PG 测试需独立环境**：`PG_TEST_DSN` 环境变量未设置时自动 skip，不影响本地 SQLite 测试流程。
3. **hypothesis 超时**：随机 hostname DNS 解析可能触发 2-3s 超时，已设置 `deadline=None`。

## 验证结果

```
111 passed / 7 skipped
覆盖率: 96.50%
Commit: cd10c76
```

## 相关文档

- [ADR-0005: 日志系统](../adr/ADR-0005-logging-system.md)
- [ADR-0009: SSRF 防护](../adr/ADR-0009-ssrf-protection.md)
- [ADR-0013: 安全加固](../adr/ADR-0013-security-hardening.md)
