# 深空载荷同余闭包审查台

对供应商提交的等式/不等式证明轨迹做**带作用域的同余闭包**核验：局部配置撤回
（`pop`）后，内层声明的等式、不等式与同余传播全部回滚，失效等式不得继续被
引用；每条声称都附带可逐级展开的「直接声明 + 同余传播」依据树。

## 目录

```
backend/          FastAPI 后端 + 可回滚同余闭包引擎（纯 Python，无外部求解器）
  app/engine.py   union/find（不做路径压缩，边携带依据）+ 撤销日志 + 作用域帧
  app/main.py     /health、/api/proofs（幂等冻结/换载荷 409）、托管前端构建产物
  tests/          有效等式、失效作用域、冲突回退、API 行为共 44 个测试
frontend/         React + Vite 页面：录入签名与 ≤180 步轨迹、展示裁决/失败位置/依据
verify/           Compose verify 服务：导入构建检查 + pytest + 真实 HTTP 冒烟
Dockerfile        frontend-build → backend / frontend(nginx) / verify 多目标
docker-compose.yml  backend + frontend + 一次性 verify
```

## 语义要点

- **项与签名**：页面先录入稳定审计标识、有限个常量和定元函数（`名称:元数`）。
  未知符号、函数/常量混用、元数不符都会定位到具体步骤并拒绝。
- **作用域**：`push` 开帧，`pop` 按撤销日志恢复全部合并边、边依据、size 与
  不等式记录；对空栈 `pop` 报错。弹出后按仍生效的等式重新补算同余闭包——
  仅在内层入图、但由外层等式蕴含的同余不会丢失；依赖内层等式的同余不会复活。
- **同余**：只有同一函数、且实参逐项等价的应用才合并；新项入图即补闭包；
  不同函数绝不合并。合并边记录是「声明触发」还是「闭包补算」。
- **冲突分级**：
  - 同一层直接 `eq` 与 `neq` 互相矛盾 → `same_level_conflict`，硬错误并定位；
  - 与外层不等式/等式冲突，或经同余传播达到的冲突 → 记录矛盾，可用无项
    `claim` 声称；`pop` 掉负责作用域后矛盾消失。
- **失败处理**：首条不成立的声称/非法步骤立即停止，返回结果只含到该步为止
  的证据（清除其后旧证据），给出 `error_position`（如 `steps[3].left/right`）。
- **重传语义**：同 `audit_id` + 同载荷（规范化 JSON 哈希，键序无关）→ 返回
  冻结结果且 `replay.replayed=true`；同标识换载荷 → `409 payload_conflict`，
  原冻结裁决不变。

## 本地开发

```bash
# 后端
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest httpx
.venv/bin/uvicorn --app-dir backend app.main:app --reload --port 8000

# 前端（dev server 代理 /api 与 /health 到 8000）
cd frontend && npm install && npm run dev
```

## Compose 启动（健康检查 + 可配置宿主端口）

```bash
cp .env.example .env      # 可改 HOST_PORT（页面，默认 8080）/ API_HOST_PORT（默认 8000）
docker compose up -d --build
# 页面:        http://localhost:${HOST_PORT:-8080}
# 后端直连:    http://localhost:${API_HOST_PORT:-8000}/health
```

## 一次性 verify（测试 + 构建检查 + HTTP 冒烟，按退出码结束）

```bash
docker compose build verify
docker compose up verify        # 退出码 0 即全部通过
# 或等其跑完并随它退出：
docker compose up --exit-code-from verify verify
```

`verify` 服务依次执行：后端导入/构建检查 → `pytest`（有效等式、失效作用域、
冲突回退、幂等/拒绝等）→ 对**运行中**的 frontend/backend 容器跑真实 HTTP 冒烟
（健康检查、页面托管、有效证明、冻结重放、409 换载荷、失效作用域定位、
未知符号、空栈弹出），然后以退出码结束，不常驻。
