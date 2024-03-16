#!/usr/bin/env python
"""
Entry point for Cloud Run Server. Can be run with
`python3 -m gunicorn app.main:app --bind :8080` on local
"""

import os
import logging

from datetime import datetime
import re
import random

import firebase_admin
from firebase_admin import credentials, firestore
from google.api_core.exceptions import NotFound

from cloudevents.http import from_http

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import BadRequest

from .utils import is_today, unmarshal
from .transcribe import transcribe
from .storage import DuckStorage


# Use the application default credentials.
cred = credentials.ApplicationDefault()

firebase_admin.initialize_app(cred)
fs_client = firestore.client()
ds = DuckStorage()

logging.basicConfig(
    format="%(asctime)s:%(message)s",
    datefmt="%H:%M:%S",
    level=logging.DEBUG,
)

app = Flask(__name__)
CORS(app)


@app.route("/sync", methods=["POST"])
def sync():
    """Sync data with clients"""
    try:
        data = request.get_json()
        user_id = data["user_id"]
        duck_id = data["duck_id"]
        prompt_ids = data["prompt_ids"]
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    logging.info("Syncing audio for %s's duck(%s)", user_id, duck_id)
    data = dict()

    # Get user's configurations for each prompt
    doc = fs_client.document(f"users/{user_id}").get()
    if not doc.exists:
        logging.error("No document for user %s", user_id)
        return (f"No document for user {user_id}", 500)

    try:
        user_info = UserInfo(user_id, doc.to_dict())
    except KeyError:
        logging.error(
            "Document format for user %s is wrong: %s", user_id, str(doc.to_dict())
        )
        return (
            "Document format for user %s is wrong: %s",
            user_id,
            str(doc.to_dict()),
            500,
        )

    for prompt_id in prompt_ids:
        prompt = user_info.prompts[prompt_id]
        prompt = prompt.replace("[user]", user_info.name).replace(
            "[hint]", user_info.hint
        )

        data[prompt_id] = {"text": prompt}

    return data


@app.route("/sync_pomo", methods=["POST"])
def sync_pomo():
    """Sync data with clients"""
    try:
        data = request.get_json()
        user_id = data["user_id"]
        duck_id = data["duck_id"]
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    logging.info("Syncing pomo duration for %s's duck(%s)", user_id, duck_id)
    data = dict()

    # Get user's configurations for each prompt
    doc = fs_client.document(f"users/{user_id}").get()
    if not doc.exists:
        logging.error("No document for user %s", user_id)
        return (f"No document for user {user_id}", 500)

    try:
        user_info = UserInfo(user_id, doc.to_dict())
    except KeyError:
        logging.error(
            "Document format for user %s is wrong: %s", user_id, str(doc.to_dict())
        )
        return (
            "Document format for user %s is wrong: %s",
            user_id,
            str(doc.to_dict()),
            500,
        )

    return {
        "focus_time": user_info.focus_time,
        "break_time": user_info.break_time,
    }


@app.route("/log/prompt", methods=["POST"])
def log_prompt():
    """Log a prompt to Firestore"""
    try:
        data = request.get_json()
        user_id = data["user_id"]
        duck_id = data["duck_id"]
        text = data["text"]
        created_at = data["created_at"]
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    logging.info("Logging a prompt for %s's duck(%s)", user_id, duck_id)

    log_data = {
        "author": "duck",
        "duck_id": duck_id,
        "content": text,
        "created_at": created_at,
    }

    _, ref = fs_client.collection(f"users/{user_id}/logs").add(log_data)

    logging.info("Added document users/%s/logs/%s", user_id, ref.id)

    return jsonify({"message": "Success"})


@app.route("/log/record", methods=["POST"])
def log_record():
    """Log a record to Firestore"""
    try:
        data = request.get_json()
        user_id = data["user_id"]
        duck_id = data["duck_id"]
        audio = data["audio"]
        created_at = data["created_at"]
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    logging.info("Logging a record for %s's duck(%s)", user_id, duck_id)

    log_data = {
        "author": "user",
        "duck_id": duck_id,
        "created_at": created_at,
    }

    _, ref = fs_client.collection(f"users/{user_id}/logs").add(log_data)
    logging.info("Added document users/%s/logs/%s", user_id, ref.id)

    ds.upload(f"logs/{user_id}/{ref.id}.wav", unmarshal(audio))

    return jsonify({"message": "Success"})


@app.route("/on_gcs_finalize", methods=["POST"])
def gcs_handler():
    """Listen to GCS finalize event with Eventarc"""
    event = from_http(request.headers, request.data)
    subject = event.get("subject")  # objects/logs/{user_id}/{record_id}.wav
    logging.info("Detected change in Cloud Storage bucket: %s", subject)

    result = re.match(r"^objects\/logs\/(.*)\/(.*)\.wav$", subject)
    if result is None or len(result.groups()) != 2:
        return (f"GCS Blob ({subject}) doesn't conform to the expected format", 200)

    user_id, record_id = result.groups()

    # Transcribe audio
    blob = ds.bucket.blob(f"logs/{user_id}/{record_id}.wav")
    text = transcribe(f"gs://{ds.bucket.name}/{blob.name}")

    # Send results to Firestore
    ref = fs_client.document(f"users/{user_id}/logs/{record_id}")
    try:
        data = {
            "audio_url": blob.public_url,
            "content": text,
        }
        if "レビュー" in text:
            data["prompt"] = text
        ref.update(data)
    except NotFound:
        logging.error("No document to update: %s", ref.path)
        return (f"No document to update: {ref.path}", 500)

    return (f"Transcription for {subject} has been successfully completed", 200)


if __name__ == "__main__":
    # get_audio("", "after_hint.wav")
    # This is used when running locally. Gunicorn is used to run the
    # application on Cloud Run. See entrypoint in Dockerfile.
    app.run(host="localhost", port=int(os.environ.get("PORT", 8080)), debug=True)


class UserInfo:
    """UserInfo"""

    def __init__(self, user_id, json_data):
        self.id = user_id
        self.name = json_data.get("name")
        self.last_active: float = json_data.get("last_active")
        self.prompts: dict[str, str] = json_data.get("prompts")  # prompt_id: text
        self.hints = json_data.get("hints")  # hint's uuid: text
        self.hint_for_today = json_data.get("hint_for_today")
        self.break_time = json_data.get("break_time")
        self.focus_time = json_data.get("focus_time")

        if not self.hint_for_today or not is_today(self.last_active):
            self.hint_for_today = random.choice(list(self.hints.keys()))
            fs_client.document(f"users/{user_id}").update(
                {
                    "last_active": datetime.now().timestamp(),
                    "hint_for_today": self.hint_for_today,
                }
            )

    @property
    def hint(self) -> str:
        """Get hint for today"""
        return self.hints[self.hint_for_today]

    def __str__(self):
        return f"UserInfo(id={self.id})"
