#!/usr/bin/env python

import logging

import os
import base64
from datetime import datetime
import re

import firebase_admin
from firebase_admin import firestore, credentials

from google.cloud import storage
from google.cloud import speech
from cloudevents.http import from_http

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
def index():
    """Receive audio data from clients"""
    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    remark_id = upload_remark_to_fs(
        user_id=data["user_id"],
        duck_id=data["duck_id"],
    )
    upload_audio_to_gcs(remark_id, data["audio"])

    return f"Remark #{remark_id} was successfully uploaded"


@app.route("/on_gcs_finalize", methods=["POST"])
def gcs_handler():
    """Listen to GCS finalize event with Eventarc"""
    event = from_http(request.headers, request.data)
    subject = event.get("subject")  # objects/audio/{remark_id}.wav
    logging.info("Detected change in Cloud Storage bucket: %s", subject)

    upload_audio_to_fs(subject)
    return (f"Detected change in Cloud Storage bucket: {subject}", 200)


def upload_audio_to_fs(subject: str):
    """Add `audio_url` to Firestore"""

    regex_result = re.match(r"^objects/(.*\.wav)$", subject)
    if regex_result is None or len(regex_result.groups()) != 1:
        logging.exception("GCS Blob (%s) doesn't seem correct", subject)
        return

    blob = bucket.get_blob(regex_result.group(1))
    if blob is None:
        logging.exception("GCS Blob(%s) was not found", subject)
        return

    regex_result = re.match(r"^.*/(.*)\.wav", blob.name)
    if regex_result is None or len(regex_result.groups()) != 1:
        logging.exception("GCS Blob (%s) exists, but its location is wrong", subject)
        return
    remark_id = regex_result.group(1)

    # Get a transcribed text
    gcs_uri = f"gs://{bucket.name}/{blob.name}"
    text = transcribe_audio(gcs_uri)

    ref = firestore_client.collection("remarks").document(remark_id)
    ref.update({"audio_url": blob.public_url, "text": text})


def transcribe_audio(gcs_uri: str) -> str:
    """Asynchronously transcribes the audio file specified by the gcs_uri.

    Args:
        gcs_uri: The Google Cloud Storage path to an audio file.

    Returns:
        The generated transcript from the audio file provided.
    """

    client = speech.SpeechClient()

    audio = speech.RecognitionAudio(uri=gcs_uri)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=44100,
        language_code="ja-JP",
    )

    operation = client.long_running_recognize(config=config, audio=audio)

    logging.info("Speech Client: Waiting for operation to complete...")
    response = operation.result(timeout=90)

    transcript_builder = []
    # Each result is for a consecutive portion of the audio. Iterate through
    # them to get the transcripts for the entire audio file.
    for result in response.results:
        # The first alternative is the most likely one for this portion.
        transcript_builder.append(f"{result.alternatives[0].transcript}\n")
        # transcript_builder.append(f"\nConfidence: {result.alternatives[0].confidence}")

    transcript = "".join(transcript_builder)
    logging.info("Speech Client: Transcript: %s", transcript)

    return transcript


def upload_remark_to_fs(user_id: str, duck_id: str) -> str:
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


def upload_audio_to_gcs(remark_id: str, data: str):
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
