"""Returns a short-lived pre-signed URL so a client can upload one image
straight to the source bucket (the file never passes through API Gateway
or Lambda)."""
import base64
import json
import os
import re
import uuid

import boto3
from botocore.config import Config

BUCKET = os.environ["SOURCE_BUCKET"]
EXPIRES_SECONDS = 300
ALLOWED = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

# SigV4 so the URL works with the Lambda role's temporary credentials
s3 = boto3.client("s3", region_name="us-east-1", config=Config(signature_version="s3v4"))


def respond(status, body):
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body)}


def handler(event, context):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    try:
        body = json.loads(raw)
    except ValueError:
        return respond(400, {"error": "Request body must be JSON"})
    if not isinstance(body, dict):
        return respond(400, {"error": "Request body must be a JSON object"})

    content_type = body.get("contentType", "")
    if content_type not in ALLOWED:
        return respond(400, {"error": "contentType must be one of: " + ", ".join(ALLOWED)})

    # Never trust the client's file name: strip any path, keep safe characters
    name = os.path.basename(str(body.get("fileName", "image")))
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", os.path.splitext(name)[0])[:40] or "image"
    key = f"uploads/{uuid.uuid4().hex[:12]}-{stem}{ALLOWED[content_type]}"

    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=EXPIRES_SECONDS,
    )
    return respond(200, {"uploadUrl": url, "key": key, "contentType": content_type,
                         "expiresInSeconds": EXPIRES_SECONDS})
