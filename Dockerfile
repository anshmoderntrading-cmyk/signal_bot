FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 STATS_FILE=/data/stats.json
RUN mkdir -p /data
CMD ["python", "bot.py"]
