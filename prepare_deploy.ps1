# Create directories
New-Item -ItemType Directory -Force -Path temp_deploy\app

# Copy necessary files
Copy-Item -Path backend\app\* -Destination temp_deploy\app\ -Recurse -Force
Copy-Item -Path backend\requirements-deploy.txt -Destination temp_deploy\requirements.txt -Force
Copy-Item -Path backend\.gcloudignore -Destination temp_deploy\ -Force

# Create a minimal Procfile if it doesn't exist
if (-not (Test-Path "temp_deploy\Procfile")) {
    Set-Content -Path "temp_deploy\Procfile" -Value "web: gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app --timeout 120"
}

Write-Host "Deployment package prepared in temp_deploy directory"
