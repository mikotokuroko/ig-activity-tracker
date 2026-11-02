FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tracker.py mcp_server.py ./
ENV TRACKER_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "tracker.py", "run"]
