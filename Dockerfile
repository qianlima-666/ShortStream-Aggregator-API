# 使用官方 Python 3.11 的轻量版镜像
FROM python:3.11-slim AS builder

# 设置非交互模式，避免 Docker 构建时的交互问题
ENV DEBIAN_FRONTEND=noninteractive

# 设置工作目录
WORKDIR /app

# 复制应用代码到容器
COPY requirements.txt /app/requirements.txt

# 使用 Aliyun 镜像源加速 pip
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ -U pip \
    && /opt/venv/bin/pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# 安装依赖
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

FROM python:3.11-slim AS runtime
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app
COPY . /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*
RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser:appuser /app
USER appuser

# 确保启动脚本可执行
RUN chmod +x start.sh
# 编译 Python 源码为字节码，并移除除启动脚本外的 .py 源码（基础代码加固）
RUN python -m compileall -b /app \
    && find /app -type f -name "*.py" ! -name "start.py" -delete

# 设置容器启动命令
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD wget -qO- http://127.0.0.1:3000/health || exit 1
CMD ["./start.sh"]

# 暴露容器端口
EXPOSE 3000
