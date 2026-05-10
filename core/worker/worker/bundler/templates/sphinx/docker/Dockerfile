FROM python:3.11-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY conf.py .
COPY *.rst ./
COPY *.md ./

RUN sphinx-build -b html . _build/html

FROM python:3.11-slim AS runner
WORKDIR /app

RUN pip install --no-cache-dir sphinx

COPY --from=base /app/_build/html ./_build/html
COPY --from=base /app/conf.py .

EXPOSE 8000

CMD ["python", "-m", "http.server", "8000", "--directory", "_build/html"]
