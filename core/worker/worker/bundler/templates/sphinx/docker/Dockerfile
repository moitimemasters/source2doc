FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY conf.py ./
COPY *.rst ./
COPY *.md ./
# Pre-rendered mermaid images (always present — sphinx defaults to svg mode).
COPY mermaid ./mermaid

# -W upgrades warnings to errors. --keep-going lets us see every problem
# in a single pass instead of bailing on the first one.
RUN sphinx-build -b html -W --keep-going . _build/html

FROM python:3.11-slim AS runner
WORKDIR /app
COPY --from=builder /app/_build/html ./html

EXPOSE 8000
CMD ["python", "-m", "http.server", "8000", "--directory", "html"]
