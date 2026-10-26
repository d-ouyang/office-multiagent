FROM python:3.13-slim

WORKDIR /app

# 国内镜像（服务器无 clashx，构建也走国内源）
# 字体两件套：noto-cjk 给 matplotlib 图表（png 渲染）；wqy-microhei 给 reportlab
# PDF 内嵌——Noto CJK 是 CFF 轮廓，reportlab TTFont 注册必败，必须 TrueType 轮廓。
# apt 源切到腾讯内网镜像：deb.debian.org 从国内出海极慢/易卡死（实测卡死过一次）
RUN (sed -i "s|deb.debian.org|mirrors.cloud.tencent.com|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true) \
    && (sed -i "s|deb.debian.org|mirrors.cloud.tencent.com|g" /etc/apt/sources.list 2>/dev/null || true) \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple -r requirements.txt

COPY app/ ./app/
COPY config/ ./config/
COPY tests/ ./tests/
COPY alembic.ini ./alembic.ini
COPY migrations/ ./migrations/

EXPOSE 8000

# 健康检查走 /api/v1/health
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
