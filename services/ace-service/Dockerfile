FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/ace-service

COPY pyproject.toml ./
COPY ace_service ./ace_service
RUN pip install --no-cache-dir . && useradd --system --uid 10001 ace

USER ace
EXPOSE 8081
HEALTHCHECK --interval=10s --timeout=2s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2)"
CMD ["uvicorn", "ace_service.service:app", "--host", "0.0.0.0", "--port", "8081"]
