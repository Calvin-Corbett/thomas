FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY thomas ./thomas

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir ".[server]"

EXPOSE 8899

CMD ["python", "-m", "thomas.server", "--host", "0.0.0.0", "--port", "8899"]
