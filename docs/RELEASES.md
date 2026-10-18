# RELEASES · office-multiagent

> 每次打 tag 生成一条 release。纪律见 PLAN-1.0.0.md §3。
> 版本格式 `vX.Y.Z-pN.M`，老 tag 永不重打。

---

## v1.0.0-p0.1 — 项目脚手架 + Docker 联动（2026-10-18）

**类型**：脚手架 / 里程碑 0
**对应计划**：PLAN-1.0.0.md Phase 0
**Tag 提交**：见 `git show v1.0.0-p0.1`

### 交付内容
- 项目骨架 `office-multiagent/`（AIAgent 工作区下）。
- `docker-compose.yml` 串起 frontend / backend / mysql / redis / chroma（同 `office-net`，健康态依赖）。
- backend：FastAPI + `/api/v1/health` 联动探测三件套（chroma 缺失降级不致命）。
- frontend：nginx 反代 `/api` + 状态页。
- `db/init.sql`：核心表 + token 池 + 模型池（设计文档 §六/§十三/§十四）。
- `backend/requirements.txt`：已验证稳定版组合（pip dry-run 零冲突）。
- `docs/PLAN-1.0.0.md`：可执行分阶段计划。
- `tests/`：冒烟（免服务）+ 集成（默认 skip）。

### 验证状态
- ✅ `pytest backend/tests/test_smoke.py` 通过（免服务）。
- ✅ `docker compose config` 通过。
- ✅ 沙箱 SSH 到远程服务器可达（点6）。
- ⏸️ 全栈实跑 / 集成测试未自动跑（点5 谨慎，交显式执行）。

### 已知遗留
- 种子密码占位 `__CHANGE_ME__`；Chroma 镜像 `latest`（生产 pin）；网关 Phase 2 补。

### 下一步
Phase 1：后端核心骨架 → `v1.0.0-p1.1`。
