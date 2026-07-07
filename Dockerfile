# COSMOS-Q — multi-stage container image
# Push to Alibaba Cloud Container Registry (ACR):
#   docker build -t registry.cn-hangzhou.aliyuncs.com/<namespace>/cosmos-q:latest .
#   docker push registry.cn-hangzhou.aliyuncs.com/<namespace>/cosmos-q:latest

# --------------------------------------------------------------------- #
# Stage 1: dependency builder
# --------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml requirements.txt ./
COPY cosmos_q/ cosmos_q/
COPY tests/ tests/

RUN pip install --upgrade pip \
 && pip install --no-cache-dir -e ".[pg,mcp]"

# --------------------------------------------------------------------- #
# Stage 2: runtime image
# --------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

# Non-root user for security
RUN groupadd -r cosmos && useradd -r -g cosmos cosmos

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY cosmos_q/ cosmos_q/
COPY pyproject.toml ./

RUN chown -R cosmos:cosmos /app
USER cosmos

# Default: run the MCP server
# Override CMD to run the CLI: docker run cosmos-q cosmos-q chat "hello"
EXPOSE 8765

CMD ["python", "-m", "cosmos_q.mcp_server"]

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8765/health').raise_for_status()"
