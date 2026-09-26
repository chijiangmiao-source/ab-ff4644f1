FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_PORT=8080

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY tests ./tests

EXPOSE 8080

# 健康检查端口可通过 APP_PORT 环境变量配置（容器内运行时展开）
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD python -c "import os,sys,urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:'+os.environ.get('APP_PORT','8080')+'/health',timeout=3).status==200 else 1)"

# 容器内监听端口由 APP_PORT 决定，宿主映射端口由 Compose 的 HOST_PORT 决定
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}"]
