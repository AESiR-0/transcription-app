FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg curl

# Set work directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of your app
COPY . .

# Run your FastAPI app (edit `main:app` if your file/module name is different)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
