#!/usr/bin/env python

import logging

import os
import base64
from datetime import datetime

import firebase_admin
from firebase_admin import firestore, credentials

from google.cloud import storage

from flask import Flask, request, jsonify
from werkzeug.exceptions import BadRequest

app = Flask(__name__)


# Use the application default credentials.
cred = credentials.ApplicationDefault()

firebase_admin.initialize_app(cred)
firestore_client = firestore.client()

gcs_client = storage.Client()
bucket = gcs_client.get_bucket("duck-audio")
if not bucket.exists():
    logging.error("There's no GCS Bucket to upload to")

logging.basicConfig(
    format="%(asctime)s:%(message)s",
    datefmt="%H:%M:%S",
    level=logging.DEBUG,
)


@app.route("/", methods=["POST"])
def upload():
    """JSON test"""
    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    remark_id = upload_remark(
        user_id=data["user_id"],
        duck_id=data["duck_id"],
    )
    upload_audio(remark_id, data["audio"])
    return f"Remark #{remark_id} was successfully uploaded"


def upload_remark(user_id: str, duck_id: str) -> str:
    """Upload remark object to firestore and returns a new id"""
    now = datetime.now()
    remark = {
        "user_id": user_id,
        "duck_id": duck_id,
        "created_at": now.timestamp(),
    }
    _, ref = firestore_client.collection("remarks").add(remark)
    logging.info(
        "Added document remarks/%s at %s", ref.id, now.strftime("%Y-%m-%d %H:%M:%S")
    )
    return ref.id


def upload_audio(remark_id: str, data: str):
    """Upload audio data to Cloud Storage"""
    blob = bucket.blob(f"audio/{remark_id}.wav")
    blob.upload_from_string(
        data=_unmarshal(data),
        content_type="audio/wav",
    )


def _unmarshal(data: str) -> bytes:
    return base64.b64decode(data.encode("utf-8"))


if __name__ == "__main__":
    # This is used when running locally. Gunicorn is used to run the
    # application on Cloud Run. See entrypoint in Dockerfile.
    app.run(host="localhost", port=int(os.environ.get("PORT", 8080)), debug=True)
