# Universal CXAS Slot-Filling Visualizer Dockerfile for Google Cloud Run
FROM python:3.11-slim

WORKDIR /app

# Copy visualizer server and HTML UI
COPY server.py /app/server.py
COPY webwidget-deploy.html /app/webwidget-deploy.html

# By default, copy the target CXAS agent folder into /app/cxas_agent
# (Or mount/override via Cloud Run volume / build context)
COPY . /app/

# Expose the port injected by Cloud Run (defaults to 8080 in Cloud Run)
ENV PORT=8080

# Launch the visualizer server pointing to the bundled agent directory
CMD ["python3", "server.py", "--app-dir", "/app/cxas_agent", "--agent", "Cashiering"]
