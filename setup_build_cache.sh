#!/bin/bash

# Exit on error
set -e

# Get the current project ID
PROJECT_ID=$(gcloud config get-value project)
BUCKET_NAME="${PROJECT_ID}_cloudbuild_cache"
SERVICE_ACCOUNT="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

# Create a storage bucket for build cache if it doesn't exist
echo "Creating Cloud Storage bucket for build cache..."
gsutil mb -l us-central1 -p $PROJECT_ID gs://$BUCKET_NAME || echo "Bucket may already exist"

# Set lifecycle policy for the cache (automatically delete objects older than 30 days)
echo "Configuring lifecycle policy for the cache..."
cat > lifecycle.json << EOL
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
EOL

gsutil lifecycle set lifecycle.json gs://$BUCKET_NAME
rm lifecycle.json

# Grant Cloud Build service account permissions to the bucket
echo "Setting IAM permissions for the cache bucket..."
gsutil iam ch serviceAccount:$SERVICE_ACCOUNT:roles/storage.objectAdmin gs://$BUCKET_NAME

echo "Build cache setup complete!"
echo "Bucket created: gs://$BUCKET_NAME"
echo "You can now use this bucket for build caching in your cloudbuild.yaml"
