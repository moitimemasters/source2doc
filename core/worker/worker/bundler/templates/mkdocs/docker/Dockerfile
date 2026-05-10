FROM python:3.11-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mkdocs.yml .
COPY docs ./docs

RUN mkdocs build

FROM python:3.11-slim AS runner
WORKDIR /app

COPY --from=base /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=base /app/site ./site
COPY --from=base /app/mkdocs.yml .
COPY --from=base /app/docs ./docs

EXPOSE 8000

ENV HOSTNAME="0.0.0.0"

CMD ["mkdocs", "serve", "--dev-addr=0.0.0.0:8000"]
