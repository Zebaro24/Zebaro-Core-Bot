FROM python:3.13-slim AS build

WORKDIR /app
COPY pyproject.toml poetry.lock* /app/

RUN apt-get update && apt-get install -y curl && \
    curl -sSL https://install.python-poetry.org | python3 - && \
    /root/.local/bin/poetry config virtualenvs.create false && \
    /root/.local/bin/poetry install --no-root --without dev --no-interaction --no-ansi

COPY . /app

FROM python:3.13-slim

WORKDIR /app
COPY --from=build /app /app

ENV PATH="/root/.local/bin:$PATH"

EXPOSE 8000
CMD ["python", "-m", "app.main"]