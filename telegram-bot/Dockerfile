FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --system bot && useradd --system --gid bot --home-dir /app --shell /usr/sbin/nologin bot
WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
COPY bot ./bot
USER bot
CMD ["python", "-m", "bot.main"]
