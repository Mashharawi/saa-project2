"""Image processor Lambda.

One function, two entry points:

* SQS event (a record from the S3 upload notification):
    - STATE_MACHINE_ARN not set -> run every step in this invocation.
    - STATE_MACHINE_ARN set     -> start a Step Functions execution instead
      (Step 8). The state machine then calls this same function once per
      step, passing {"step": "validate" | "resize" | "watermark" | "store"}.
* Direct invocation with a "step" key (used by Step Functions).

Steps hand work to each other through S3 and DynamoDB, so they behave the
same in both modes.
"""
import hashlib
import io
import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone

import boto3
from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]
TABLE_NAME = os.environ["TABLE_NAME"]
TOPIC_ARN = os.environ["TOPIC_ARN"]
STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")
WATERMARK_TEXT = os.environ.get("WATERMARK_TEXT", "SAA Project 2")

MAX_BYTES = 10 * 1024 * 1024        # reject uploads over 10 MB
MAX_PIXELS = 40_000_000             # reject images over 40 megapixels
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
FULL_SIZE = 1280                    # longest side of the main image
THUMB_SIZE = 256                    # longest side of the thumbnail

s3 = boto3.client("s3")
sns = boto3.client("sns")
sfn = boto3.client("stepfunctions")
table = boto3.resource("dynamodb").Table(TABLE_NAME)


class ValidationError(Exception):
    """The upload is not acceptable. Retrying will not help."""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_object(bucket, key):
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def to_jpeg_bytes(img, quality=85):
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


# --------------------------------------------------------------- steps
def validate(job):
    head = s3.head_object(Bucket=job["bucket"], Key=job["key"])
    if head["ContentLength"] > MAX_BYTES:
        raise ValidationError(f"File is {head['ContentLength']} bytes; limit is {MAX_BYTES}")

    data = read_object(job["bucket"], job["key"])
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()                       # cheap integrity check
        img = Image.open(io.BytesIO(data))  # verify() leaves the image unusable
    except Exception as exc:
        raise ValidationError("File is not a readable image") from exc

    if img.format not in ALLOWED_FORMATS:
        raise ValidationError(f"Format {img.format} not allowed; use JPEG, PNG or WEBP")
    if img.width * img.height > MAX_PIXELS:
        raise ValidationError(f"Image is {img.width}x{img.height}; too many pixels")

    table.put_item(Item={
        "imageId": job["imageId"],
        "sourceKey": job["key"],
        "status": "PROCESSING",
        "uploadTime": now(),
        "width": img.width,
        "height": img.height,
        "format": img.format,
    })
    return {**job, "width": img.width, "height": img.height, "format": img.format}


def resize(job):
    img = Image.open(io.BytesIO(read_object(job["bucket"], job["key"])))
    img = ImageOps.exif_transpose(img)     # respect phone-camera rotation

    thumb = img.copy()
    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE))
    s3.put_object(Bucket=PROCESSED_BUCKET, Key=f"thumbnails/{job['imageId']}.jpg",
                  Body=to_jpeg_bytes(thumb), ContentType="image/jpeg")

    full = img.copy()
    full.thumbnail((FULL_SIZE, FULL_SIZE))
    s3.put_object(Bucket=PROCESSED_BUCKET, Key=f"work/{job['imageId']}.jpg",
                  Body=to_jpeg_bytes(full), ContentType="image/jpeg")
    return job


def add_watermark(img, text):
    base = img.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    size = max(18, base.width // 18)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:                       # very old Pillow
        font = ImageFont.load_default()
    stroke = max(1, size // 10)             # dark outline: readable on any background
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    margin = size // 2
    x = base.width - (right - left) - margin - left
    y = base.height - (bottom - top) - margin - top
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 235),
              stroke_width=stroke, stroke_fill=(0, 0, 0, 210))
    return Image.alpha_composite(base, overlay).convert("RGB")


def watermark(job):
    work_key = f"work/{job['imageId']}.jpg"
    img = Image.open(io.BytesIO(read_object(PROCESSED_BUCKET, work_key)))
    s3.put_object(Bucket=PROCESSED_BUCKET, Key=f"images/{job['imageId']}.jpg",
                  Body=to_jpeg_bytes(add_watermark(img, WATERMARK_TEXT)),
                  ContentType="image/jpeg")
    s3.delete_object(Bucket=PROCESSED_BUCKET, Key=work_key)
    return job


def store(job):
    table.update_item(
        Key={"imageId": job["imageId"]},
        # "status" is a DynamoDB reserved word, so it is aliased as #s
        UpdateExpression="SET #s = :s, imageKey = :i, thumbnailKey = :t, completedTime = :c",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "COMPLETED",
            ":i": f"images/{job['imageId']}.jpg",
            ":t": f"thumbnails/{job['imageId']}.jpg",
            ":c": now(),
        },
    )
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="Image processed",
        Message=(f"Image {job['imageId']} finished.\n"
                 f"Source: {job['key']} ({job.get('width')}x{job.get('height')})\n"
                 f"Output: images/{job['imageId']}.jpg"),
    )
    return job


def fail(event):
    """Permanent failure: record it and tell the subscriber."""
    reason = event.get("error", "unknown error")
    if isinstance(reason, dict):            # Step Functions Catch output
        cause = reason.get("Cause") or ""
        try:                                # Cause is JSON text from the failed Lambda
            parsed = json.loads(cause)
            reason = parsed.get("errorMessage", cause) if isinstance(parsed, dict) else cause
        except ValueError:
            reason = cause or reason.get("Error", "unknown error")
    table.update_item(
        Key={"imageId": event["imageId"]},
        UpdateExpression="SET #s = :s, errorMessage = :e, completedTime = :c, sourceKey = :k",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "FAILED", ":e": str(reason)[:500], ":c": now(),
                                   ":k": event.get("key", "unknown")},
    )
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="Image processing failed",
        Message=f"Image {event['imageId']} ({event.get('key', '?')}) failed.\nReason: {reason}",
    )
    return event


STEPS = {"validate": validate, "resize": resize, "watermark": watermark,
         "store": store, "fail": fail}


def run_pipeline(job):
    for step in (validate, resize, watermark, store):
        job = step(job)
    return job


# ---------------------------------------------------------- SQS entry
def make_job(s3_record):
    bucket = s3_record["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(s3_record["s3"]["object"]["key"])
    sequencer = s3_record["s3"]["object"].get("sequencer", "")
    # Same upload -> same ID, so SQS redeliveries and retries update one item
    image_id = hashlib.sha256(f"{bucket}/{key}/{sequencer}".encode()).hexdigest()[:16]
    return {"imageId": image_id, "bucket": bucket, "key": key}


def handle_record(job):
    if STATE_MACHINE_ARN:
        try:
            sfn.start_execution(stateMachineArn=STATE_MACHINE_ARN,
                                name=job["imageId"], input=json.dumps(job))
        except sfn.exceptions.ExecutionAlreadyExists:
            logger.info("Execution %s already exists; duplicate message", job["imageId"])
        return
    try:
        run_pipeline(job)
    except ValidationError as exc:
        logger.warning("Rejected %s: %s", job["key"], exc)
        fail({**job, "error": str(exc)})    # permanent: do not retry
    except Exception:
        logger.exception("Transient failure on %s; SQS will retry", job["key"])
        raise                               # after 3 tries it lands in the DLQ


def handler(event, context):
    if "Records" in event:                  # from SQS
        for record in event["Records"]:
            body = json.loads(record["body"])
            for s3_record in body.get("Records", []):   # s3:TestEvent has none
                handle_record(make_job(s3_record))
        return {"ok": True}

    step = STEPS.get(event.get("step"))     # from Step Functions
    if step is None:
        raise ValueError(f"Unknown step: {event.get('step')}")
    return step(event)
