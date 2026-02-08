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

CMD ["python", "-m", "clinicaflow.demo_server"]

