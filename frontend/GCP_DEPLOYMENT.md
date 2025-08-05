# GCP Deployment Guide

This guide explains how to deploy the Next.js application to Google Cloud Platform (GCP) App Engine.

## Prerequisites

1. Install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
2. Install [Node.js](https://nodejs.org/) (v18 or later)
3. Install [npm](https://www.npmjs.com/) (comes with Node.js)
4. A Google Cloud Platform account with billing enabled
5. A GCP project with App Engine enabled

## Setup Instructions

### 1. Initialize Google Cloud SDK

```bash
gcloud init
```

### 2. Set your GCP project

```bash
gcloud config set project YOUR_PROJECT_ID
```

### 3. Install Dependencies

```bash
npm install
```

### 4. Configure Environment Variables

Create a `.env.production` file with your production environment variables:

```env
NODE_ENV=production
NEXT_PUBLIC_APP_URL=https://YOUR_PROJECT_ID.uc.r.appspot.com
NEXT_PUBLIC_API_URL=https://YOUR_API_URL
# Add other production environment variables here
```

## Deployment

### Option 1: Using npm script (recommended for most users)

```bash
# Build and deploy with interactive prompts
npm run deploy:gcp
```

### Option 2: Manual Deployment

1. Build the application:
   ```bash
   npm run build
   ```

2. Deploy to GCP:
   ```bash
   gcloud app deploy --quiet --promote --stop-previous-version
   ```

### Option 3: CI/CD Pipeline

For CI/CD pipelines, you can use the following command:

```bash
npm run deploy:gcp:ci
```

## Post-Deployment

1. Verify deployment:
   ```bash
   gcloud app browse
   ```

2. View logs:
   ```bash
   gcloud app logs tail -s default
   ```

## Troubleshooting

- **Deployment fails**: Check the logs with `gcloud app logs read`
- **App not starting**: Ensure all environment variables are set in GCP Console
- **Build errors**: Try running `npm run build` locally first to catch any issues

## Maintenance

To update the application, simply run the deployment command again. The `--promote` flag will automatically route traffic to the new version.

## Cleanup

To delete the deployed application:

```bash
gcloud app services delete default
```

## Support

For additional help, refer to the [GCP App Engine documentation](https://cloud.google.com/appengine/docs/standard/nodejs).
