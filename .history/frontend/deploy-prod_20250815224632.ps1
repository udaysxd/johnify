# PowerShell script to build and deploy Next.js frontend to Google Cloud Run using .env.production
# Save this as deploy-prod.ps1 in your frontend directory

# Set NODE_ENV to production
$env:NODE_ENV = "production"

# Load .env.production variables into the environment (robust parsing)
if (Test-Path .env.production) {
    $lines = Get-Content .env.production | Where-Object { $_ -notmatch "^\s*($|#)" }
    foreach ($line in $lines) {
        if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            $name = $matches[1]
            $value = $matches[2]
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
            Set-Item -Path "env:$name" -Value $value
        }
    }
} else {
    Write-Host ".env.production not found. Aborting."
    exit 1
}

# Print loaded environment variables for verification
Write-Host "BACKEND_URL: $env:BACKEND_URL"
Write-Host "NEXT_PUBLIC_BACKEND_URL: $env:NEXT_PUBLIC_BACKEND_URL"

# Build Next.js app with production environment
npm run build

# Submit build to Google Cloud Build
$IMAGE="gcr.io/optimum-shape-467809-h9/johnify-frontend"
gcloud builds submit --tag $IMAGE

# Deploy to Cloud Run using only build-time environment variables
gcloud run deploy johnify-frontend `
  --image $IMAGE `
  --platform managed `
  --region us-central1 `
  --allow-unauthenticated `
  --port 3000
