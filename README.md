# ShortURL - 短链接服务

生产级短链接服务，基于 FastAPI + SQLite，支持容器化部署。

## 🚀 快速开始

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 访问 API 文档
# http://localhost:8000/docs
```

### Docker 部署

```bash
# 构建镜像
docker build -t shorturl:latest .

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

---

## 📚 API 文档

### 基础信息

- **Base URL**: `http://localhost:8000`
- **认证**: API Key（请求头 `X-API-Key`）
- **响应格式**: 统一 Envelope
  ```json
  {
    "success": true,
    "data": { ... },
    "error": null
  }
  ```

---

### 端点列表

#### 1. 创建短链接

**POST** `/api/shorten`

**请求体：**
```json
{
  "url": "https://example.com/very/long/url",
  "custom_code": "optional-custom-code",  // 可选
  "expires_at": "2026-12-31T23:59:59Z"  // 可选
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "code": "abc123",
    "short_url": "http://localhost:8000/abc123",
    "original_url": "https://example.com/very/long/url",
    "created_at": "2026-06-12T15:30:00Z",
    "expires_at": "2026-12-31T23:59:59Z"
  },
  "error": null
}
```

---

#### 2. 重定向

**GET** `/{code}`

- 301 重定向至原始 URL
- 自动递增点击计数

---

#### 3. 查询短链接信息

**GET** `/api/info/{code}`

**响应：**
```json
{
  "success": true,
  "data": {
    "code": "abc123",
    "original_url": "https://example.com/",
    "created_at": "2026-06-12T15:30:00Z",
    "expires_at": null,
    "click_count": 42
  },
  "error": null
}
```

---

#### 4. 删除短链接

**DELETE** `/api/delete/{code}`

**响应：**
```json
{
  "success": true,
  "data": {
    "message": "Short URL deleted successfully"
  },
  "error": null
}
```

---

#### 5. 批量创建

**POST** `/api/batch`

**请求体：**
```json
{
  "urls": [
    "https://example.com/page1",
    "https://example.com/page2"
  ]
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "results": [
      {
        "original_url": "https://example.com/page1",
        "code": "abc123",
        "short_url": "http://localhost:8000/abc123"
      },
      {
        "original_url": "https://example.com/page2",
        "code": "def456",
        "short_url": "http://localhost:8000/def456"
      }
    ]
  },
  "error": null
}
```

---

#### 6. 健康检查

**GET** `/health`

**响应：**
```json
{
  "status": "healthy",
  "timestamp": "2026-06-12T15:30:00Z"
}
```

---

#### 7. Prometheus 指标

**GET** `/metrics`

- 返回 Prometheus 格式指标
- 包含：请求计数、延迟、活跃链接数

---

## 🧪 测试

```bash
# 运行所有测试
pytest tests/ -v

# 检查覆盖率
pytest tests/ --cov=app --cov-report=term-missing

# 当前覆盖率：96.50%（81 个测试）
```

---

## 🐳 容器化

### Dockerfile 多阶段构建

```dockerfile
# 构建阶段
FROM python:3.12-slim AS builder
RUN pip install --user -r requirements.txt

# 生产阶段
FROM python:3.12-slim
RUN adduser --disabled-password --gecos "" appuser
USER appuser
WORKDIR /app
COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appuser . .
CMD ["tini", "--", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:///data/shorturl.db
      - SECRET_KEY=${SECRET_KEY}
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

---

## 🔧 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | 数据库连接 | `sqlite:///data/shorturl.db` |
| `SECRET_KEY` | JWT 签名密钥 | **必须设置** |
| `API_KEY` | API 访问密钥 | `dev-api-key-12345` |

---

## 📊 CI/CD

GitHub Actions 自动化门禁（5 道）：

1. **test-and-lint** - pytest + flake8
2. **security-scan** - Bandit + Safety
3. **build-docker** - Docker 镜像构建
4. **integration-test** - 端到端测试
5. **deploy-staging** - 自动部署预发环境

---

## 📁 项目结构

```
shorturl/
├── app/                    # 应用代码
│   ├── main.py             # FastAPI 入口
│   ├── database.py         # 数据库连接
│   ├── models.py           # Pydantic 模型
│   ├── schemas.py          # API 契约
│   └── auth.py             # 认证逻辑
├── tests/                  # 测试文件
│   ├── test_main.py
│   ├── test_database.py
│   └── ...
├── docker-compose.yml      # 容器编排
├── Dockerfile              # 多阶段构建
├── requirements.txt        # Python 依赖
└── run_tests.ps1          # 测试脚本
```

---

## 📝 开发指南

### 添加新功能

1. 在 `app/` 下创建模块
2. 在 `tests/` 下添加对应测试
3. 更新 API 文档（本 README）
4. 提交 PR（需通过 CI 门禁）

### 代码规范

- **格式化**: `black .`
- **Lint**: `flake8 app/`
- **类型检查**: `mypy app/`

---

## 🛡️ 安全

- ✅ API Key 认证
- ✅ SQL 注入防护（参数化查询）
- ✅ XSS 防护（输出编码）
- ✅ Rate Limiting（计划中）

---

## 📄 许可证

MIT License

---

## 👥 贡献者

- **后端开发**: BeDev
- **架构设计**: Arch
- **测试**: QA
- **运维**: DevOps
- **代码审查**: CR

---

## 📮 联系方式

- **GitHub**: [vmmll001728/vmmll-shorturl-prod](https://github.com/vmmll001728/vmmll-shorturl-prod)
- **Issue**: [提交问题](https://github.com/vmmll001728/vmmll-shorturl-prod/issues)
