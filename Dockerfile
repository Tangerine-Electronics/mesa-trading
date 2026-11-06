FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml README.md setup.py MANIFEST.in ./
COPY src ./src
COPY config ./config

# pip install deja el código en site-packages; estas rutas apuntan al config copiado.
ENV MESA_DESK_CONFIG=/app/config/desk.yaml \
    MESA_PROMOTION_CONFIG=/app/config/promotion.yaml \
    MESA_FEES_CONFIG=/app/config/fees.yaml \
    MESA_POLICY_CONFIG=/app/config/policy.yaml

RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["python", "-m", "mesa_trading.cli.api"]
