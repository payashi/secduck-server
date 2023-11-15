#!/usr/bin/env python

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
from werkzeug.exceptions import BadRequest

from .utils import marshal, is_today
from .storage import upload_audio, get_uri, synthesize_audio
from .transcribe import transcribe

# Use the application default credentials.
cred = credentials.ApplicationDefault()

firebase_admin.initialize_app(cred)
fs_client = firestore.client()

logging.basicConfig(
    format="%(asctime)s:%(message)s",
    datefmt="%H:%M:%S",
    level=logging.DEBUG,
)

app = Flask(__name__)


@app.route("/", methods=["POST"])
def index():
    """Receive audio data from clients"""
    try:
        data = request.get_json()
        user_id = data["user_id"]
        duck_id = data["duck_id"]
        audio = data["audio"]
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    remark = {
        "user_id": user_id,
        "duck_id": duck_id,
        "created_at": datetime.now().timestamp(),
    }
    _, ref = fs_client.collection("remarks").add(remark)
    logging.info("Added document remarks/%s", ref.id)

    upload_audio(f"remarks/{ref.id}.wav", audio)

    return f"Remark #{ref.id} was successfully uploaded"


@app.route("/start_work", methods=["GET"])
def start_work():
    """Send audio data to start work"""
    user_id = request.args.get("user_id")

    logging.info("Receive `start_work` request from %s", user_id)

    doc = fs_client.document(f"users/{user_id}").get()
    if not doc.exists:
        logging.error("No document for user %s", user_id)
        return (f"No document for user {user_id}", 500)

    data = doc.to_dict()
    try:
        last_active = data["last_active"]
        prompts = data["prompts"]
        hints = data["hints"]
    except KeyError:
        logging.error("Document format for user %s is wrong: %s", user_id, str(data))
        return (f"Document format for user {user_id} is wrong: {str(data)}", 500)

    if not is_today(last_active):
        hint_id, hint_text = random.choice(list(hints.items()))
        prompt_ids = {
            tag: list(prompt.keys())[0] for tag, prompt in list(prompts.items())
        }
        prompt_texts = {
            tag: list(prompt.values())[0] for tag, prompt in list(prompts.items())
        }
        # Today's first prompt
        audio = synthesize_audio(
            f"prompts/{prompt_ids['hello']}.wav",
            f"prompts/{prompt_ids['before_hint']}.wav",
            f"hints/{hint_id}.wav",
            f"prompts/{prompt_ids['after_hint']}.wav",
            f"prompts/{prompt_ids['start_work']}.wav",
        )
        text = "\n".join(
            [
                prompt_texts["hello"],
                prompt_texts["before_hint"] + hint_text + prompt_texts["after_hint"],
                prompt_texts["start_work"],
            ]
        )
    else:
        audio = synthesize_audio(f"prompts/{prompt_ids['start_work']}.wav")
        text = "\n".join([prompt_texts["start_work"]])

    prompt = {
        "audio": marshal(audio),
        "text": text,
    }
    return jsonify(prompt)


@app.route("/on_gcs_finalize", methods=["POST"])
def gcs_handler():
    """Listen to GCS finalize event with Eventarc"""
    event = from_http(request.headers, request.data)
    subject = event.get("subject")  # objects/audio/{remark_id}.wav
    logging.info("Detected change in Cloud Storage bucket: %s", subject)

    result = re.match(r"^objects\/(remarks\/.*)\.wav)$", subject)
    if result is None or len(result.groups()) != 1:
        return (f"GCS Blob ({subject}) doesn't seem correct", 500)
    docpath = result.group(1)  #  'remarks/{remark_id}'

    # Transcribe audio
    gcs_uri, url = get_uri(docpath + ".wav")
    text = transcribe(gcs_uri)

    # Send results to Firestore
    ref = fs_client.document(docpath)
    try:
        ref.update({"audio_url": url, "text": text})
    except NotFound:
        logging.error("No document to update: %s", docpath)

    return (f"Transcription for {subject} has been successfully completed", 200)


if __name__ == "__main__":
    # get_audio("", "after_hint.wav")
    # This is used when running locally. Gunicorn is used to run the
    # application on Cloud Run. See entrypoint in Dockerfile.
    app.run(host="localhost", port=int(os.environ.get("PORT", 8080)), debug=True)
