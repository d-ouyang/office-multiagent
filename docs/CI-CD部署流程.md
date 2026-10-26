# office-multiagent · CI/CD 部署流程（自托管 Runner 版）

> 目标：`git push` 打 tag（或手动触发）→ 服务器自动构建并上线 → 健康检查通过才算成功。
> 套路与 nianan-site / 1024 的 M5 一致：**自托管 runner 装在服务器上**，代码由 runner 从 GitHub 拉取（runner 自带凭据，服务器不需要配 git）。
> 阅读前提：服务器 42.192.111.82、部署目录 `/opt/office`、共享 RAG 中间件形态（`docker-compose.prod.yml`）。

---

## 〇、前置条件（一次性，已完成的不用重做）

| 项 | 状态 |
| --- | --- |
| 服务器上有 `/opt/office` + 可用的 `.env`（chmod 600） | ✅ p6.42 已建 |
| 服务器上已能 `docker compose -f docker-compose.prod.yml up -d` | ✅ |
| GitHub 仓库 `d-ouyang/office-multiagent` | ✅ |
| 服务器出网可达 github.com（runner 拉代码用） | ✅（现有两个 runner 在用） |
| 首次部署已完成（库表、Caddy 站点在位） | ✅ p6.42/p6.43 |

---

## 一、在 GitHub 上注册 office 专用自托管 Runner（约 10 分钟）

服务器上已有 `actions-runner-site`（nianan-site 用）。**建议给 office 单独建一个**（目录隔离、并发互不影响）：

1. 打开 `https://github.com/d-ouyang/office-multiagent` → **Settings → Actions → Runners → New self-hosted runner**。
2. 选 Linux / x86_64，页面会给出一段带临时 token 的命令。SSH 到服务器照做：

```bash
ssh ubuntu@42.192.111.82
# 1) 建目录并下载 runner（版本以 GitHub 页面为准；服务器现有 runner 为 2.337.0，建议同版）
mkdir -p /opt/actions-runner-office && cd /opt/actions-runner-office
curl -o actions-runner-linux-x64-2.337.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.337.0/actions-runner-linux-x64-2.337.0.tar.gz
tar xzf ./actions-runner-linux-x64-2.337.0.tar.gz
```

> **国内下载不动？**（deb.debian.org 同款问题）在本地开代理下载后再传上去：
> ```bash
> # 本地 Mac（proxy_on 之后）：
> curl -o actions-runner-linux-x64-2.337.0.tar.gz -L \
>   https://github.com/actions/runner/releases/download/v2.337.0/actions-runner-linux-x64-2.337.0.tar.gz
> shasum -a 256 actions-runner-linux-x64-2.337.0.tar.gz   # 与 GitHub 页面的校验值比对
> scp actions-runner-linux-x64-2.337.0.tar.gz ubuntu@42.192.111.82:/opt/actions-runner-office/
> # 然后到服务器上从 `tar xzf ...` 那步继续，跳过 curl。
> ```

# 2) 注册（--url 和 token 从 GitHub 页面复制；labels 填 office-deploy）
./config.sh --url https://github.com/d-ouyang/office-multiagent \
  --token <页面上的token> --name office-runner --labels office-deploy \
  --work /opt/actions-runner-office/_work --unattended

# 3) 装成 systemd 服务（开机自启、断线自动重连）
sudo ./svc.sh install ubuntu && sudo ./svc.sh start
sudo ./svc.sh status   # 确认 active (running)
```

3. 回到 GitHub 页面确认 runner 出现且 **Idle**。

---

## 二、提交 workflow 文件（仓库里加一个文件）

新建 `.github/workflows/deploy-office.yml`，内容如下（可直接复制）：

```yaml
name: deploy-office

on:
  push:
    tags: ["v*"]          # 打 tag 即部署（老 tag 永不重打，tag 即版本）
  workflow_dispatch:       # 也允许手动点按钮部署

concurrency:
  group: office-deploy     # 防止两次部署互相踩
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: [self-hosted, office-deploy]
    timeout-minutes: 40
    steps:
      - name: 拉取代码
        uses: actions/checkout@v4
        with: { clean: true }

      - name: 同步代码到部署目录（绝不覆盖 .env）
        run: |
          rsync -a --delete \
            --exclude ".env" --exclude ".env.*" \
            --exclude "backend/data/upload" \
            --exclude "backend/data/*.csv" \
            --exclude "backend/data/*.sql" \
            --exclude "backend/data/*.py" \
            ./ /opt/office/
          # 说明：数据/种子/env 都以 /opt/office 本地为准，不用仓库覆盖

      - name: 构建镜像
        working-directory: /opt/office
        run: docker compose -f docker-compose.prod.yml build

      - name: 数据库迁移（有新迁移时自动应用；无则 no-op）
        working-directory: /opt/office
        run: docker compose -f docker-compose.prod.yml run --rm office-backend alembic upgrade head

      - name: 上线
        working-directory: /opt/office
        run: docker compose -f docker-compose.prod.yml up -d --remove-orphans

      - name: 健康检查（不过 2 分钟就判失败）
        working-directory: /opt/office
        run: |
          for i in $(seq 1 24); do
            code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 \
              -H "X-Internal-Token: skip" http://127.0.0.1:3001/api/v1/health || true)
            # 健康检查走网关；网关对 /health 放行，无需内部令牌
            if [ "$code" = "200" ]; then echo "健康检查通过"; exit 0; fi
            sleep 5
          done
          echo "健康检查超时"; exit 1

      - name: 冒烟（首页 200）
        run: |
          code=$(curl -s -o /dev/null -w "%{http_code}" -m 10 https://office.nianan.site/)
          [ "$code" = "200" ] || { echo "首页 $code"; exit 1; }
          echo "冒烟通过"
```

> 两个注意点：
> ① **`.env` 永远只存在于服务器** `/opt/office/.env`，workflow 里所有同步命令都排除它；
> ② 迁移步骤用的是 `alembic upgrade head`（追加迁移没问题；0001 的多语句 bug 只影响"全新空库"，首次部署已用 init.sql+stamp 处理过，不会再走）。

提交并推送：

```bash
cd /Users/ouyangding/Desktop/AIAgent/office-multiagent
git add .github/workflows/deploy-office.yml && git commit -m "ci: office 打 tag 自动部署" && git push origin master
```

---

## 三、日常发布流程（你以后每次上线就这两步）

```bash
# 1) 本地改完代码、测试过了，按纪律走版本号 + tag
git add ... && git commit -m "feat(pN.M): ..."
git tag vX.Y.Z-pN.M
git push origin master --tags

# 2) 看进度
open https://github.com/d-ouyang/office-multiagent/actions
# runner 日志也可以在服务器上看：
#   sudo journalctl -u actions.runner.*-office-runner -f
```

成功标准：Actions 页面全绿 + 冒烟输出「冒烟通过」。线上即新版本。

---

## 四、验证一次完整流程（建议你亲手走一遍）

1. 先去 **Settings → Actions → Runners** 确认 `office-runner` 是 Idle；
2. 打一个不影响功能的文档 tag 走全流程：
   ```bash
   git tag v1.0.0-pN.M && git push origin v1.0.0-pN.M
   ```
3. 在 Actions 页面点进这次运行，逐步看四个 step 的输出；
4. 结束后服务器上核对：
   ```bash
   docker ps --format "{{.Names}}\t{{.Status}}" | grep office   # 三容器 healthy
   curl -s http://127.0.0.1:3001/api/v1/health | head -c 200
   ```
5. 在 Actions 页面用 **workflow_dispatch** 再手动触发一次，确认手动路径也通。

---

## 五、回滚（出问题时）

```bash
# 方式一：回到上一个 tag（推荐）
ssh ubuntu@42.192.111.82
cd /opt/office
git -C /opt/actions-runner-office/_work/... # 不用管工作区，直接用镜像回退：
docker compose -f docker-compose.prod.yml down
# 用上一个版本的代码重新构建：本地把上一次的 tag rsync 上去（--exclude .env），再
docker compose -f docker-compose.prod.yml up -d --build
# 方式二：只回滚单个镜像（更快）
docker tag office-backend:latest office-backend:bad && \
docker tag office-backend:<上个tag的镜像> office-backend:latest && \
docker compose -f docker-compose.prod.yml up -d --force-recreate office-backend
```

> 数据库回滚要单独评估（`alembic downgrade` 有风险）；追加型迁移一般不需要回滚数据。

---

## 六、与 RAG 的隔离保证（为什么 office 部署不会影响 RAG）

1. **compose 项目隔离**：office 的 build/up 只作用于 `/opt/office/docker-compose.prod.yml` 里的三个容器，RAG 的七容器不受影响。
2. **服务名全局唯一**（p6.43 铁律）：office 服务名带 `office-` 前缀，共享网络 `rag-qa-system_default` 上不会与 RAG 的 `backend/gateway/frontend` DNS 别名撞车。
3. **共享中间件只读复用**：mysql/redis/chroma 容器归 RAG 的 compose 管，office 永远不重建它们；office 的库/redis db/向量 collection 全部隔离。
4. **构建资源**：构建会在服务器上短暂吃 CPU/内存（前端 vite build 最重）， runner 并发已用 `concurrency` 锁死为串行；建议避开 RAG 高峰时段发版。
