import os
from pathlib import Path
from typing import Optional

# Lazy import to avoid dependency when not needed (e.g., local dev without GCS)
try:
    from google.cloud import storage  # type: ignore
except Exception:  # pragma: no cover
    storage = None  # Will be validated at runtime when needed

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"

ASSETS_BUCKET = os.getenv("ASSETS_BUCKET", "")
ASSETS_PREFIX = os.getenv("ASSETS_PREFIX", "content").strip("/")


def _require_gcs():
    if not IS_PRODUCTION:
        raise RuntimeError("GCS operations are only enabled in production environment")
    if storage is None:
        raise RuntimeError("google-cloud-storage is not installed")
    if not ASSETS_BUCKET:
        raise RuntimeError("ASSETS_BUCKET env var is required in production")


def _client() -> "storage.Client":
    _require_gcs()
    return storage.Client()


def _bucket(client: "storage.Client") -> "storage.Bucket":
    bucket = client.bucket(ASSETS_BUCKET)
    return bucket


def gcs_object_path(*parts: str) -> str:
    prefix = ASSETS_PREFIX
    parts_clean = [p.strip("/") for p in parts if p and str(p).strip("/")]
    path = "/".join([prefix] + parts_clean) if prefix else "/".join(parts_clean)
    return path


def upload_file(local_path: str | Path, *, object_path: str, content_type: Optional[str] = None, make_public: bool = True) -> str:
    """
    Upload a local file to the configured GCS bucket.

    Args:
        local_path: Path to the local file to upload
        object_path: Path inside the bucket (without leading slash)
        content_type: Optional content-type
        make_public: Whether to make the object publicly readable

    Returns:
        The gs:// URL of the uploaded object
    """
    lp = Path(local_path)
    if not lp.exists():
        raise FileNotFoundError(f"Local file not found: {lp}")

    client = _client()
    bucket = _bucket(client)
    blob = bucket.blob(object_path)

    blob.upload_from_filename(str(lp), content_type=content_type)

    if make_public:
        # If uniform bucket-level access is ON, this will be a no-op for individual object ACLs,
        # but the object will be readable if the bucket IAM grants allUsers->Storage Object Viewer.
        try:
            blob.make_public()
        except Exception:
            # Ignore if not permitted; callers can still generate signed URLs if required
            pass

    return f"gs://{ASSETS_BUCKET}/{object_path}"


def public_url(object_path: str) -> str:
    """
    Build a public URL for an object. Assumes object is readable publicly.
    """
    object_path = object_path.strip("/")
    return f"https://storage.googleapis.com/{ASSETS_BUCKET}/{object_path}"


def maybe_upload_and_url(local_path: str | Path, *, parts: list[str], content_type: Optional[str] = None, make_public: bool = True) -> dict:
    """
    Convenience helper: in production, upload local_path to gcs://{bucket}/{prefix}/{parts...}
    and return both gs:// and https URLs; in non-production, return filesystem path URLs for parity.

    Returns dict with keys: { 'object_path', 'gs_url', 'https_url', 'used_gcs': bool }
    """
    lp = Path(local_path)
    object_path = gcs_object_path(*parts)

    if IS_PRODUCTION:
        gs_url = upload_file(lp, object_path=object_path, content_type=content_type, make_public=make_public)
        return {
            "object_path": object_path,
            "gs_url": gs_url,
            "https_url": public_url(object_path),
            "used_gcs": True,
        }
    else:
        # Dev: don't upload, return file:// path and a pseudo URL
        return {
            "object_path": object_path,
            "gs_url": f"file://{lp.resolve()}",
            "https_url": str(lp.resolve()),
            "used_gcs": False,
        }
