FROM python:3.12-slim AS deps
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime-base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src/backend
COPY --from=deps /install /usr/local
RUN useradd --create-home --uid 10001 appuser
USER appuser

FROM runtime-base AS portal
COPY --chown=appuser:appuser src/backend ./src/backend
COPY --chown=appuser:appuser src/frontend ./src/frontend
CMD ["python", "-m", "services.portal.server"]

FROM runtime-base AS agent
COPY --chown=appuser:appuser src/backend ./src/backend
CMD ["python", "-m", "services.agent.server"]

FROM runtime-base AS mcp
COPY --chown=appuser:appuser src/backend ./src/backend
CMD ["python", "-m", "services.mcp_server.server"]
