#!/bin/bash
set -e

# Configuration
PROJECT_ID="optimum-shape-467809-h9"  # Replace with your GCP project ID
SERVICE_NAME="johnify-frontend"
REGION="us-central1"  # or your preferred region
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"

# Ensure user is logged in to gcloud
echo "Checking gcloud authentication..."
gcloud auth list

echo "Building Docker image..."
docker build -t ${IMAGE_NAME} .

echo "Pushing image to Google Container Registry..."
docker push ${IMAGE_NAME}

echo "Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_NAME} \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars="NEXT_PUBLIC_BACKEND_URL=https://johnify-backend-873155673176.us-central1.run.app"  # Replace with your backend URL

echo "Deployment complete! Your service is now live at:"
gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format="value(status.url)"
