# Use an official Python runtime as a parent image
FROM python:3.10-alpine AS builder

# Install build dependencies
RUN apk add --no-cache build-base

# Set the working directory
WORKDIR /usr/src/app

# Copy requirements.txt
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Start fresh with only the minimal Python runtime.
FROM python:3.10-alpine AS runtime

# Set working directory for the final application
WORKDIR /usr/src/app

# Copy the Python environment dependencies from the builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

# Copy the rest of the application code
COPY . .

# Expose the service port
EXPOSE 3002

# Set environment variables for the product-service
ENV PORT=3002

# Start the product-service
CMD ["python", "app.py"]