# Google Cloud Storage (GCS) setup for Johnify assets

This backend can upload generated videos and thumbnails to GCS in production and return public HTTPS URLs.

## Required environment variables

Add the following to the Cloud Run service (and optionally local .env for parity):

- ENVIRONMENT=production
- ASSETS_BUCKET=assets-johnify            # Your GCS bucket name
- ASSETS_PREFIX=content                   # Optional prefix inside the bucket

Locally (development), uploads are skipped and local filesystem paths are used.

## IAM permissions

The Cloud Run service account must have permissions on the bucket:

- roles/storage.objectAdmin on the bucket (write, update object ACLs if used)
- roles/storage.legacyBucketReader or roles/storage.viewer for listing/reads (optional)

Grant on the specific bucket:

```
gcloud storage buckets add-iam-policy-binding gs://assets-johnify \
  --member=serviceAccount:YOUR_CLOUD_RUN_SA \
  --role=roles/storage.objectAdmin
```

Replace `YOUR_CLOUD_RUN_SA` with the service account email (e.g., `project-number-compute@developer.gserviceaccount.com` or a dedicated SA).

## Public access policy

This code assumes objects can be publicly read. You can enable either:

1) Uniform bucket-level access (recommended) + IAM grant allUsers Storage Object Viewer

```
gcloud storage buckets update gs://assets-johnify --uniform-bucket-level-access

gcloud storage buckets add-iam-policy-binding gs://assets-johnify \
  --member=allUsers \
  --role=roles/storage.objectViewer
```

2) Per-object ACLs (default). The code calls `blob.make_public()` after upload. If uniform access is ON, this is a no-op; ensure (1) is configured to make objects readable.

## How URLs are built

- gs:// URL stored in DB (production) for `post_path` consistency
- Public HTTPS returned to clients: `https://storage.googleapis.com/{ASSETS_BUCKET}/{ASSETS_PREFIX}/...`

## Cleanup policy

In production, after successful upload and DB write, local temp directories used for generation under `/tmp` are removed automatically.

## Troubleshooting

- 403 when fetching public URL: ensure bucket has public read (see Public access policy above)
- Upload errors: verify `ASSETS_BUCKET`, `ASSETS_PREFIX`, and Cloud Run SA IAM
- Missing google-cloud-storage: ensure `google-cloud-storage` is in backend requirements
