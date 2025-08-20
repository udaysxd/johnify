# PowerShell script to set up Google Cloud Build cache
# Run this script in PowerShell with Google Cloud SDK installed and authenticated

# Exit on error
$ErrorActionPreference = "Stop"

# Get the current project ID
$PROJECT_ID = gcloud config get-value project
$BUCKET_NAME = "${PROJECT_ID}_cloudbuild_cache"

# Get project number and construct service account email
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$SERVICE_ACCOUNT = "${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

Write-Host "Project ID: $PROJECT_ID"
Write-Host "Project Number: $PROJECT_NUMBER"
Write-Host "Service Account: $SERVICE_ACCOUNT"

# Create a storage bucket for build cache if it doesn't exist
Write-Host "Creating Cloud Storage bucket for build cache..."
try {
    gsutil mb -l us-central1 -p $PROJECT_ID "gs://$BUCKET_NAME"
    Write-Host "Bucket created: gs://$BUCKET_NAME"
} catch {
    Write-Host "Bucket may already exist or another error occurred. Continuing..."
}

# Set lifecycle policy for the cache (automatically delete objects older than 30 days)
Write-Host "Configuring lifecycle policy for the cache..."
$lifecycleConfig = @"
{
  "rule": [
    {
      "action": {
        "type": "Delete"
      },
      "condition": {
        "age": 30,
        "isLive": true
      }
    }
  ]
}
"@

$tempFile = [System.IO.Path]::GetTempFileName()
$lifecycleConfig | Out-File -FilePath $tempFile -Encoding ascii

try {
    gsutil lifecycle set $tempFile "gs://$BUCKET_NAME"
    Remove-Item $tempFile
    Write-Host "Lifecycle policy set successfully."
} catch {
    Write-Host "Error setting lifecycle policy: $_"
    if (Test-Path $tempFile) { Remove-Item $tempFile }
}

# Grant Cloud Build service account permissions to the bucket
Write-Host "Setting IAM permissions for the cache bucket..."
try {
    gsutil iam ch "serviceAccount:${SERVICE_ACCOUNT}:roles/storage.objectAdmin" "gs://$BUCKET_NAME"
    Write-Host "IAM permissions set successfully."
} catch {
    Write-Host "Error setting IAM permissions: $_"
}

Write-Host "`nBuild cache setup complete!"
Write-Host "Bucket: gs://$BUCKET_NAME"
Write-Host "Service Account: $SERVICE_ACCOUNT"
Write-Host "`nYou can now use this bucket for build caching in your cloudbuild.yaml"
