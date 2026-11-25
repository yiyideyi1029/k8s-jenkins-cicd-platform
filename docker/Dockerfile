# Stage 1: Builder 阶段（编译安装依赖）
FROM python:3.11-slim AS builder

WORKDIR /build
COPY app/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime 精简运行阶段（仅保留运行时依赖与非 root 用户）
FROM python:3.11-alpine

LABEL maintainer="Ren Junjie"
WORKDIR /app

# 从 builder 阶段拷贝已安装依赖，剔除编译缓存与冗余工具
COPY --from=builder /install /usr/local
COPY app/main.py /app/main.py

# 安全基线：使用非 root 用户运行容器
RUN adduser -D -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "main:app"]