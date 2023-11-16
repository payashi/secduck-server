#!/usr/bin/env python
"""
Entry point for Cloud Run Server. Can be run with
`python3 -m gunicorn app.main:app --bind :8080` on local
"""

import os
import logging
import uuid

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
from .storage import upload_audio, get_uri, concatenate_audio
from .transcribe import transcribe
from .synthesize import synthesize

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
        "from": "user",
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
    duck_id = request.args.get("duck_id")

    logging.info("Receive `start_work` request from %s", user_id)

    user_ref = fs_client.document(f"users/{user_id}")
    user_doc = user_ref.get()
    if not user_doc.exists:
        logging.error("No document for user %s", user_id)
        return (f"No document for user {user_id}", 500)

    data = user_doc.to_dict()

    user_ref.update(
        {"last_active": datetime.now().timestamp()},
    )
    try:
        last_active = data["last_active"]
        prompts = data["prompts"]
        hints = data["hints"]
    except KeyError:
        logging.error("Document format for user %s is wrong: %s", user_id, str(data))
        return (f"Document format for user {user_id} is wrong: {str(data)}", 500)

    prompt_ids = {tag: list(prompt.keys())[0] for tag, prompt in list(prompts.items())}
    prompt_texts = {
        tag: list(prompt.values())[0] for tag, prompt in list(prompts.items())
    }

    if not is_today(last_active):
        hint_id, hint_text = random.choice(list(hints.items()))

        user_ref.update({"hint_for_today": hint_id})
        # Today's first prompt
        audio = concatenate_audio(
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
        audio = concatenate_audio(f"prompts/{prompt_ids['start_work']}.wav")
        text = "\n".join([prompt_texts["start_work"]])

    prompt = {
        "audio": marshal(audio),
        "text": text,
    }

    fs_client.collection("remarks").add(
        {
            "from": "duck",
            "user_id": user_id,
            "duck_id": duck_id,
            "text": text,
            "created_at": datetime.now().timestamp(),
        }
    )
    return jsonify(prompt)


@app.route("/pause_work", methods=["GET"])
def pause_work():
    """Send audio data to pause work"""
    user_id = request.args.get("user_id")
    duck_id = request.args.get("duck_id")

    logging.info("Receive `pause_work` request from %s", user_id)

    doc = fs_client.document(f"users/{user_id}").get()
    doc = fs_client.document(f"users/{user_id}").get()
    if not doc.exists:
        logging.error("No document for user %s", user_id)
        return (f"No document for user {user_id}", 500)

    data = doc.to_dict()
    try:
        prompts = data["prompts"]
    except KeyError:
        logging.error("Document format for user %s is wrong: %s", user_id, str(data))
        return (f"Document format for user {user_id} is wrong: {str(data)}", 500)

    prompt_ids = {tag: list(prompt.keys())[0] for tag, prompt in list(prompts.items())}
    prompt_texts = {
        tag: list(prompt.values())[0] for tag, prompt in list(prompts.items())
    }

    audio = concatenate_audio(f"prompts/{prompt_ids['pause_work']}.wav")
    text = prompt_texts["pause_work"]

    prompt = {
        "audio": marshal(audio),
        "text": text,
    }

    fs_client.collection("remarks").add(
        {
            "from": "duck",
            "user_id": user_id,
            "duck_id": duck_id,
            "text": text,
            "created_at": datetime.now().timestamp(),
        }
    )
    return jsonify(prompt)


@app.route("/start_review", methods=["GET"])
def start_review():
    """Send audio data to pause work"""
    user_id = request.args.get("user_id")
    duck_id = request.args.get("duck_id")

    logging.info("Receive `start_review` request from %s", user_id)

    user_ref = fs_client.document(f"users/{user_id}")
    user_doc = user_ref.get()
    if not user_doc.exists:
        logging.error("No document for user %s", user_id)
        return (f"No document for user {user_id}", 500)

    data = user_doc.to_dict()
    try:
        prompts = data["prompts"]
        hints = data["hints"]
        hint_for_today = data["hint_for_today"]
    except KeyError:
        logging.error("Document format for user %s is wrong: %s", user_id, str(data))
        return (f"Document format for user {user_id} is wrong: {str(data)}", 500)

    prompt_ids = {tag: list(prompt.keys())[0] for tag, prompt in list(prompts.items())}
    prompt_texts = {
        tag: list(prompt.values())[0] for tag, prompt in list(prompts.items())
    }

    audio = concatenate_audio(
        f"prompts/{prompt_ids['bye']}.wav",
        f"prompts/{prompt_ids['before_review']}.wav",
        f"hints/{hint_for_today}.wav",
        f"prompts/{prompt_ids['after_review']}.wav",
    )
    # text = prompt_texts["pause_work"]
    text = "\n".join(
        [
            prompt_texts["bye"],
            f'{prompt_texts["before_review"]}'
            f' "{hints[hint_for_today]}" '
            f'{prompt_texts["after_review"]}',
        ]
    )

    prompt = {
        "audio": marshal(audio),
        "text": text,
    }

    fs_client.collection("remarks").add(
        {
            "from": "duck",
            "user_id": user_id,
            "duck_id": duck_id,
            "text": text,
            "created_at": datetime.now().timestamp(),
        }
    )
    return jsonify(prompt)


@app.route("/users/hints", methods=["POST"])
def create_hint():
    """Create a hint"""
    try:
        data = request.get_json()
        user_id = data["user_id"]
        hint_text = data["hint_text"]
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    ref = fs_client.document(f"users/{user_id}")
    user_info = ref.get().to_dict()
    hints = user_info["hints"]
    hint_id = str(uuid.uuid4())
    hints[hint_id] = hint_text
    ref.update({"hints": hints})

    upload_audio(f"hints/{hint_id}.wav", synthesize(hint_text))

    return f"Successfully created a new hint: {hint_id}"


@app.route("/users/hints", methods=["DELETE"])
def delete_hint():
    """Create a hint"""
    try:
        data = request.get_json()
        user_id = data["user_id"]
        hint_id = data["hint_id"]
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    ref = fs_client.document(f"users/{user_id}")
    user_info = ref.get().to_dict()
    hints = user_info["hints"]
    del hints[hint_id]
    ref.update({"hints": hints})

    return f"Successfully deleted a hint: {hint_id}"


@app.route("/on_gcs_finalize", methods=["POST"])
def gcs_handler():
    """Listen to GCS finalize event with Eventarc"""
    event = from_http(request.headers, request.data)
    subject = event.get("subject")  # objects/audio/{remark_id}.wav
    logging.info("Detected change in Cloud Storage bucket: %s", subject)

    result = re.match(r"^objects\/(remarks\/.*)\.wav$", subject)
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
