FROM python:3.12.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY server/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home qdrop && mkdir /data && chown qdrop:qdrop /data
COPY server /app
USER 10001:10001
CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m app.run"]
