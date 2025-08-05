#!/bin/bash

# Exit on error
set -e

echo "🔍 Checking for required tools..."
if ! command -v gcloud &> /dev/null; then
    echo "❌ Google Cloud SDK (gcloud) is not installed. Please install it first."
    echo "   Visit: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "❌ Node.js and npm are required but not installed."
    echo "   Visit: https://nodejs.org/"
    exit 1
fi

echo "🔑 Authenticating with Google Cloud..."
gcloud auth login

echo "📦 Installing dependencies..."
npm install

# Build the Next.js application
echo "🏗️  Building the application..."
npm run build

# Deploy to GCP App Engine
echo "🚀 Deploying to Google Cloud Platform..."
gcloud app deploy --quiet --promote --stop-previous-version

echo "✅ Deployment complete!"
echo "   Your app should be live at: https://$(gcloud config get-value project).uc.r.appspot.com"
