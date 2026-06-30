FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Base SQLite sur le volume persistant (voir docker-compose.yml / Coolify storage)
ENV DB_PATH=/data/pronobot.db

CMD ["python", "bot.py"]
