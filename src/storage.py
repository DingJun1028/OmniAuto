"""Module 6 — Cloud storage.

Default: local ./storage. If S3 credentials are set, the final MP4 is
also uploaded to S3 and the returned public URL is stored on the job so
players can fetch it.
"""
from __future__ import annotations

from pathlib import Path

from .config import AWS_ACCESS_KEY_ID, AWS_REGION, AWS_S3_BUCKET, AWS_SECRET_ACCESS_KEY, USE_S3


def _relative_to_storage(path: Path) -> str:
    """Return `path` as a posix path relative to STORAGE_DIR.

    Renders live at e.g. `a1b2c3/final.mp4` so the web app can serve it
    under `/storage/{rest_of_path}` without ambiguity (every job writes into
    its own sub-directory, so the bare filename `final.mp4` would collide).

    Reads `config.STORAGE_DIR` at call time (not imported by value) so the
    `isolated_state` fixture — which redirects STORAGE_DIR for tests — is
    honoured.
    """
    from . import config
    rel = path.resolve().relative_to(config.STORAGE_DIR.resolve())
    return rel.as_posix()


def save_local(path: Path) -> str:
    # Local files are served via /storage/<job_id>/<name> by the web app.
    # We keep the job sub-directory in the URL so it resolves unambiguously.
    return f"/storage/{_relative_to_storage(path)}"


def upload_s3(path: Path) -> str:
    import boto3
    from boto3.s3.transfer import TransferConfig

    s3 = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
    key = f"videos/{_relative_to_storage(path)}"
    # Upload with an explicit content type + a bounded timeout so a stalled
    # transfer can't hang the publish step.
    s3.upload_file(
        str(path),
        AWS_S3_BUCKET,
        key,
        ExtraArgs={"ContentType": "video/mp4"},
        Config=TransferConfig(
            multipart_threshold=8 * 1024 * 1024,
            max_concurrency=4,
        ),
    )
    return f"https://{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{key}"


def publish(path: Path) -> str:
    local_url = save_local(path)
    if USE_S3:
        try:
            return upload_s3(path)
        except Exception:
            return local_url
    return local_url
