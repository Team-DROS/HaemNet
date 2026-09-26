# Use an official lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set Python path so that `import backend.x` works correctly
ENV PYTHONPATH=/app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend source code into the container under /app/backend
COPY . /app/backend

# Expose the FastAPI port
EXPOSE 8000

# Command to run the application using Uvicorn with 4 workers for production concurrency
# --loop asyncio is required: PyMongo's async client hangs on uvloop.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--loop", "asyncio", "--workers", "1"]
