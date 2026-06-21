FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY . .

# HuggingFace Spaces serves on the port set by app_port in README front matter.
# Write debug logs to a guaranteed-writable location.
ENV MOVIE_AGENT_DEBUG_LOG_DIR=/tmp/llm_logs
EXPOSE 7860

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
