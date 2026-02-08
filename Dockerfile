FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY clinicaflow/ clinicaflow/
COPY examples/ examples/
COPY docs/ docs/

RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -e .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2).read(); sys.exit(0)"

RUN useradd --create-home --uid 10001 appuser
USER appuser

CMD ["python", "-m", "clinicaflow.demo_server"]
