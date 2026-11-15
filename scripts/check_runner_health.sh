#!/usr/bin/env bash
# runner 健康监控（v2.2.0-p1.13 / F4）——GitHub self-hosted runner 静默挂掉的自动探活。
#
# 背景：runner（VM-0-14-ubuntu.service）两次复发"systemd active 但不领任务"
#（症状：log 见 "A session for this runner already exists" 后退出；表现为 tag 部署
# 一直 queued 无人领取）。本脚本每 5 分钟探一次，两个信号任一命中即重启：
#   ① runner 离线 / last_contact 超 10 分钟（actions/runners API）
#   ② 任意 workflow run 处于 queued 超过 10 分钟（兜底，覆盖 API 状态误报）
# 命中后：systemctl restart runner + 写日志 +（可选）POST budget_alert_webhook_url。
#
# 安装（服务器）：见文件尾注释；token 放 /opt/office/.github-token（chmod 600）。
set -u
REPO="d-ouyang/office-multiagent"
RUNNER_NAME="VM-0-14-ubuntu"
TOKEN_FILE="/opt/office/.github-token"
LOG_TAG="runner-health"
GRACE_MIN=10

TOKEN=$(cat "$TOKEN_FILE" 2>/dev/null || true)
if [ -z "$TOKEN" ]; then
  logger -t "$LOG_TAG" "跳过：$TOKEN_FILE 不存在或为空"
  exit 0
fi
AUTH="Authorization: token $TOKEN"

# ①（已裁剪）：actions/runners API 需要 PAT 的 Administration 权限，fine-grained
# token 会 403——只用 ② queued 兜底信号即可（健康时无 queued，runner 挂了必然 queued）。

# ② 兜底：queued 超时的 run
QUEUED_MIN=$(curl -sS -m 15 -H "$AUTH" "https://api.github.com/repos/$REPO/actions/runs?per_page=5" | python3 -c "
import json,sys,datetime
try:
    data=json.load(sys.stdin)
    worst=0
    now=datetime.datetime.now(datetime.timezone.utc)
    for r in data.get('workflow_runs',[]):
        if r.get('status')=='queued':
            t=datetime.datetime.fromisoformat((r.get('run_started_at') or '').replace('Z','+00:00'))
            worst=max(worst,int((now-t).total_seconds()//60))
    print(worst)
except Exception:
    print(0)")
UNHEALTHY=0
REASON=""
if [ "$QUEUED_MIN" -gt "$GRACE_MIN" ]; then
  UNHEALTHY=1
  REASON="有 run queued ${QUEUED_MIN}min 无人领取"
fi

if [ "$UNHEALTHY" = "0" ]; then
  exit 0
fi

logger -t "$LOG_TAG" "不健康：$REASON → 重启 runner"
sudo -n systemctl restart "actions.runner.d-ouyang-office-multiagent.${RUNNER_NAME}.service"
sleep 8
NEW_STATUS=$(systemctl is-active "actions.runner.d-ouyang-office-multiagent.${RUNNER_NAME}.service")
logger -t "$LOG_TAG" "重启后状态：$NEW_STATUS（原因：$REASON）"

# 可选 webhook 通知（复用 B3 的告警配置，若存在）
WEBHOOK=$(grep -E '^BUDGET_ALERT_WEBHOOK_URL=' /opt/office/.env 2>/dev/null | cut -d= -f2- || true)
if [ -n "$WEBHOOK" ]; then
  curl -sS -m 5 -X POST "$WEBHOOK" -H 'content-type: application/json' \
    -d "{\"kind\":\"runner_health\",\"detail\":{\"reason\":\"$REASON\",\"service_after\":\"$NEW_STATUS\"}}" \
    >/dev/null 2>&1 || true
fi

# 安装（服务器一次性执行）：
#   sudo install -m 755 check_runner_health.sh /opt/office/scripts/check_runner_health.sh
#   echo "<PAT>" | sudo tee /opt/office/.github-token >/dev/null && sudo chmod 600 /opt/office/.github-token
#   echo '*/5 * * * * /opt/office/scripts/check_runner_health.sh' | sudo tee /etc/cron.d/runner-health
#   # 注意 /etc/cron.d 需要用户字段：*/5 * * * * ubuntu /opt/office/scripts/check_runner_health.sh
