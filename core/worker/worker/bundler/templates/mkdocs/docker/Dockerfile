FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY mkdocs.yml ./
COPY docs ./docs

# Fail early on broken nav / missing files instead of serving a 404 site.
RUN mkdocs build --strict

EXPOSE 8000

CMD ["mkdocs", "serve", "--dev-addr=0.0.0.0:8000"]
