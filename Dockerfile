FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src:/app
COPY pyproject.toml README.md ./
COPY src ./src
# Mock mode needs no Azure SDKs. For azure mode build with: --build-arg EXTRAS="[azure]"
ARG EXTRAS=""
RUN pip install --no-cache-dir ".${EXTRAS}"
COPY . .
RUN useradd --create-home app && mkdir -p /app/.data && chown -R app /app/.data
USER app
