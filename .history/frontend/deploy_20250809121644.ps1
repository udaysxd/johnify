# Configuration
$PROJECT_ID = "optimum-shape-467809-h9"
$SERVICE_NAME = "johnify-frontend"
$REGION = "us-central1"
$IMAGE_NAME = "gcr.io/$PROJECT_ID/$SERVICE_NAME"
$BACKEND_URL = "https://johnify-backend-873155673176.us-central1.run.app"

# Check gcloud authentication
Write-Host "Checking gcloud authentication..."
gcloud auth list

# Build the Docker image
Write-Host "Building Docker image..."
docker build -t $IMAGE_NAME .

# Push to Google Container Registry
Write-Host "Pushing image to Google Container Registry..."
docker push $IMAGE_NAME

# Deploy to Cloud Run
Write-Host "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME `
  --image $IMAGE_NAME `
  --platform managed `
  --region $REGION `
  --allow-unauthenticated `
  --port 8080 `
  --set-env-vars="NEXT_PUBLIC_BACKEND_URL=$BACKEND_URL"

# Get the service URL
$SERVICE_URL = gcloud run services describe $SERVICE_NAME --region $REGION --format="value(status.url)"
Write-Host "Deployment complete! Your service is now live at: $SERVICE_URL"
