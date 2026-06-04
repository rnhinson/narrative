# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# OpenShift runs containers as an arbitrary non-root UID.
# g=u lets that UID write to /app/data even without a fixed uid.
RUN mkdir -p /app/data && chown -R nobody:root /app && chmod -R g=u /app

WORKDIR /app

COPY --from=build /install /usr/local
COPY --chown=nobody:root src ./src

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SOCKET_MODE=false
ENV PORT=3000
ENV DATA_DIR=/app/data

EXPOSE 3000

USER nobody

CMD ["python", "src/app.py"]
