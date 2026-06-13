# Mini PRD: 添加 /api/version 端点

## 1. 背景与目标

- **背景**：服务需要对外暴露版本信息，便于运维、监控和客户端识别当前部署的版本。
- **目标**：GET /api/version 返回版本元数据，状态码 200。
- **范围**：仅实现版本端点，不涉及其他 API。

---

## 2. 用户故事（User Story）

**US-001**: 作为 **运维/监控人员**，我希望访问 `/api/version` 获取当前服务的版本信息，以便确认部署状态或进行健康检查。

> As an Ops/Monitoring engineer, I want to query `/api/version` to retrieve the service version metadata, so that I can verify the deployed version during deployments or health checks.

**验收标准**：

- Given 服务已启动, When 客户端发送 `GET /api/version`, Then 返回 HTTP 200，响应体为 `{"version": "1.0.0", "service": "shorturl"}`
- Given 服务已启动, When `Accept` 为 `application/json`, Then Content-Type 为 `application/json`
- Given 服务已启动, When 请求 `/api/version`, Then 响应延迟 < 100ms

---

## 3. 验收标准（Acceptance Criteria）

| 编号 | 描述 | 优先级 |
|------|------|--------|
| AC-001 | GET `/api/version` 返回 HTTP 200 | P0 |
| AC-002 | 响应体为 `{"version": "1.0.0", "service": "shorturl"}` | P0 |
| AC-003 | Content-Type 为 `application/json` | P0 |
| AC-004 | 单元测试覆盖该端点，验证状态码和响应体 | P0 |

---

## 4. 功能列表

### P3 - 小功能

- [ ] 实现 `GET /api/version` 端点，返回固定版本信息
- [ ] 添加单元测试，验证响应状态码和 JSON 结构

---

## 5. 技术说明

- **实现位置**：建议在路由层添加新路由，响应内容硬编码或从配置文件读取
- **测试框架**：建议使用项目已有测试框架（如 Jest / JUnit / pytest 等）
- **测试用例**：
  1. 调用 `/api/version`，断言状态码为 200
  2. 断言响应 JSON 的 `version` 字段为 `"1.0.0"`
  3. 断言响应 JSON 的 `service` 字段为 `"shorturl"`

---

## 6. 里程碑

- **M1（1 day）**：实现 `/api/version` 端点 + 单元测试，Code Review 通过

---

## 7. 开放问题

- Q1: 版本号是否改为从 `package.json` / `VERSION` 文件动态读取，而非硬编码？
- Q2: 是否需要支持 `GET /api/health` 作为配套健康检查端点？