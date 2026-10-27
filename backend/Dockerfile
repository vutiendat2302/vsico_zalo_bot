FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ ./src/
COPY docs/ ./docs/
COPY tests/fixtures/ ./tests/fixtures/

EXPOSE 8000

CMD ["python", "-m", "nhaxe_bot.main", "--serve", "--port", "8000"]
