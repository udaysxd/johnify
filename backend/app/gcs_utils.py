import os
import logging
from datetime import timedelta
from pathlib import Path
from typing import Optional, Tuple, Dict

import google.auth
from google.auth import iam as google_iam
from google.auth.transport import requests as google_requests
from google.oauth2 import service_account
import urllib.request as _urlreq

# Lazy import to avoid dependency when not needed (e.g., local dev without GCS)
try:
    from google.cloud import storage  # type: ignore
except Exception:  # pragma: no cover
    storage = None  # Will be validated at runtime when needed

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"

ASSETS_BUCKET = os.getenv("ASSETS_BUCKET", "")
ASSETS_PREFIX = os.getenv("ASSETS_PREFIX", "content").strip("/")

logger = logging.getLogger(__name__)


def _require_gcs():
    if not IS_PRODUCTION:
        raise RuntimeError("GCS operations are only enabled in production environment")
    if storage is None:
        raise RuntimeError("google-cloud-storage is not installed")
    if not ASSETS_BUCKET:
        raise RuntimeError("ASSETS_BUCKET env var is required in production")


def _get_service_account_email(credentials) -> str:
    """Return the actual service account email for signing.

    Some compute credentials expose 'default' or omit the email. In that case,
    try metadata server to resolve the bound service account email.
    """
    sa_email = getattr(credentials, "service_account_email", None)
    if isinstance(sa_email, str) and "@" in sa_email:
        return sa_email

    # Try metadata server (Cloud Run / GCE)
    try:
        req = _urlreq.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
        )
        with _urlreq.urlopen(req, timeout=2) as resp:
            value = resp.read().decode("utf-8").strip()
            if value and "@" in value:
                return value
    except Exception:
        pass

    raise RuntimeError("Unable to determine service account email for IAM signing")


def _signer() -> google_iam.Signer:
    """Create an IAM Signer for service-account-based V4 URL signing on Cloud Run.

    Requires the active service account to have roles/iam.serviceAccountTokenCreator.
    """
    credentials, _ = google.auth.default()
    sa_email = _get_service_account_email(credentials)
    request = google_requests.Request()
    return google_iam.Signer(request, credentials, sa_email)


def _signing_credentials() -> service_account.Credentials:
    """Return service-account-style Credentials that sign via IAM Signer.

    Storage signed URL helpers expect credentials that can sign bytes and
    expose service account email. This wraps the IAM Signer accordingly.
    """
    credentials, _ = google.auth.default()
    sa_email = _get_service_account_email(credentials)
    request = google_requests.Request()
    signer = google_iam.Signer(request, credentials, sa_email)
    # token_uri isn't used for signing, but the class requires it.
    return service_account.Credentials(
        signer=signer,
        service_account_email=sa_email,
        token_uri="https://oauth2.googleapis.com/token",
    )


def _client() -> "storage.Client":
    _require_gcs()
    # Use default creds (Cloud Run provides Compute Engine creds without a private key)
    credentials, project = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_write"])

    cred_cls = credentials.__class__.__name__
    sa_email = getattr(credentials, "service_account_email", None)
    logger.info("[gcs] Using credentials class=%s service_account_email=%s project=%s", cred_cls, sa_email, project)

    # Use default credentials; use explicit IAM Signer only when generating signed URLs.
    return storage.Client(project=project)


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

    # Dev: don't upload, return file:// path and a pseudo URL
    return {
        "object_path": object_path,
        "gs_url": f"file://{lp.resolve()}",
        "https_url": str(lp.resolve()),
        "used_gcs": False,
    }


def generate_direct_upload_url(
    *,
    bucket_name: str,
    object_path: str,
    content_type: str,
    expires: timedelta = timedelta(hours=1),
    resumable: bool = False,
) -> Tuple[str, Dict[str, str]]:
    """Generate a signed URL and required headers for direct uploads to GCS.

    Args:
        bucket_name: Target GCS bucket name.
        object_path: Path inside the bucket (without leading slash).
        content_type: MIME type for the upload.
        expires: Expiration window for the signed URL.
        resumable: If True, request a resumable session (POST with x-goog-resumable).

    Returns:
        Tuple of (signed_url, headers_dict) where headers must be included when
        issuing the upload request.
    """

    if storage is None:
        raise RuntimeError("google-cloud-storage is not installed")
    if not bucket_name:
        raise RuntimeError("bucket_name is required")
    if not object_path:
        raise RuntimeError("object_path is required")

    client = _client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_path)

    headers: Dict[str, str] = {"Content-Type": content_type}

    try:
        logger.info(
            "[gcs] Generating signed URL bucket=%s object=%s resumable=%s content_type=%s",
            bucket_name,
            object_path,
            resumable,
            content_type,
        )
        signing_creds = _signing_credentials()
        if resumable:
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=expires,
                method="POST",
                content_type=content_type,
                headers={"x-goog-resumable": "start"},
                credentials=signing_creds,
            )
            headers["x-goog-resumable"] = "start"
        else:
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=expires,
                method="PUT",
                content_type=content_type,
                credentials=signing_creds,
            )
    except Exception as exc:
        logger.exception(
            "[gcs] Signed URL generation failed for bucket=%s object=%s resumable=%s",
            bucket_name, object_path, resumable
        )
        raise

    return signed_url, headers
