FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/main.py .
COPY server/install-agent.sh .
COPY agent/agent.py .

COPY agent/ferpek_lens /app/ferpek_lens

VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
