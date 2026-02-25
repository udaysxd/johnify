# Configuration
$PROJECT_ID = "johnify-476816"
$SERVICE_NAME = "johnify-frontend"
$REGION = "us-central1"
$IMAGE_NAME = "gcr.io/$PROJECT_ID/$SERVICE_NAME"
$BACKEND_URL = "https://johnify-backend-398050553559.us-central1.run.app"

# Enable detailed error reporting
$ErrorActionPreference = "Stop"

# Function to log messages
function Write-LogMessage {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
}

try {
    # Set the active project
    Write-LogMessage "Setting active project to $PROJECT_ID"
    gcloud config set project $PROJECT_ID

    # Check authentication
    Write-LogMessage "Checking authentication..."
    $auth = gcloud auth list --format="value(account)" --filter="status=ACTIVE"
    if (-not $auth) {
        throw "No active Google Cloud account found. Please run 'gcloud auth login'"
    }
    Write-LogMessage "Authenticated as: $auth"

    # Build the Docker image with build arguments
    Write-LogMessage "Building Docker image..."
    docker build `
        --build-arg NEXT_PUBLIC_BACKEND_URL="$BACKEND_URL" `
        -t $IMAGE_NAME .
    if ($LASTEXITCODE -ne 0) { throw "Docker build failed" }

    # Configure Docker to use gcloud as credential helper
    Write-LogMessage "Configuring Docker to use gcloud..."
    gcloud auth configure-docker --quiet

    # Push the image
    Write-LogMessage "Pushing image to Google Container Registry..."
    docker push $IMAGE_NAME
    if ($LASTEXITCODE -ne 0) { throw "Docker push failed" }

    # Deploy with all environment variables and secrets
    Write-LogMessage "Deploying to Cloud Run..."
    
    # First, check if secret exists
    $secretExists = $false
    try {
        $null = gcloud secrets describe nextauth-secret --format="value(name)" 2>$null
        $secretExists = $true
    } catch {
        Write-LogMessage "Warning: nextauth-secret not found in Secret Manager."
    }
    
    # Build the deployment command
    $deployCommand = "gcloud run deploy $SERVICE_NAME " +
        "--image $IMAGE_NAME " +
        "--platform managed " +
        "--region $REGION " +
        "--allow-unauthenticated " +
        "--port 8080 " +
        "--set-env-vars=NEXT_PUBLIC_BACKEND_URL=$BACKEND_URL"
    
    # Add secret if it exists
    if ($secretExists) {
        $deployCommand += " --update-secrets=NEXTAUTH_SECRET=nextauth-secret:latest"
    } else {
        # Use a dummy secret if the real one doesn't exist
        $deployCommand += " --set-env-vars=NEXTAUTH_SECRET=dummy-secret-for-initial-deploy"
        Write-LogMessage "Using a dummy NEXTAUTH_SECRET. Please update with a real secret later."
    }
    
    # Execute the deployment
    Invoke-Expression $deployCommand
    if ($LASTEXITCODE -ne 0) { throw "Cloud Run deployment failed" }
    if ($LASTEXITCODE -ne 0) { throw "Cloud Run deployment failed" }

    # Get the service URL
    $SERVICE_URL = gcloud run services describe $SERVICE_NAME --region $REGION --format="value(status.url)"
    Write-LogMessage "Deployment complete! Your service is now live at: $SERVICE_URL"
    
    # Open the service in the default browser
    Start-Process $SERVICE_URL
}
catch {
    Write-LogMessage "ERROR: $_"
    exit 1
}
