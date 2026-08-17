FROM python:3.12-slim

WORKDIR /app

# Copy project metadata and source first so the package can be installed correctly
COPY pyproject.toml ./
COPY app/ ./app/
COPY data/ ./data/

# Install dependencies after the app package is present
RUN pip install --no-cache-dir -e .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
