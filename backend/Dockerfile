FROM python:3.13-slim

WORKDIR /app

# 国内镜像（服务器无 clashx，构建也走国内源）
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple -r requirements.txt

COPY app/ ./app/
COPY config/ ./config/
COPY tests/ ./tests/

EXPOSE 8000

# 健康检查走 /api/v1/health
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
