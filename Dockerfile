FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY demo ./demo
RUN pip install --no-cache-dir . && useradd --create-home appuser && mkdir -p data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8765
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--no-access-log"]
