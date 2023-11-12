#!/usr/bin/env python

import logging


import os
from datetime import datetime

import firebase_admin
from firebase_admin import firestore, credentials

from flask import Flask, request, jsonify
from werkzeug.exceptions import BadRequest

app = Flask(__name__)


# Use the application default credentials.
cred = credentials.ApplicationDefault()

firebase_admin.initialize_app(cred)
db = firestore.client()

logging.basicConfig(
    format="%(asctime)s:%(message)s",
    datefmt="%H:%M:%S",
    level=logging.DEBUG,
)


@app.route("/", methods=["POST"])
def index():
    """JSON test"""
    try:
        data = request.get_json()
    except BadRequest:
        return jsonify({"error": "Invalid JSON"}), 400

    remark_id = upload_remark(
        user_id=data["user_id"],
        duck_id=data["duck_id"],
    )
    return f"Server: Got {data['user_id']}"


def upload_remark(user_id: str, duck_id: str) -> str:
    """Upload remark object to firestore and returns a new id"""
    now = datetime.now()
    remark = {
        "user_id": user_id,
        "duck_id": duck_id,
        "created_at": now.timestamp(),
    }
    _, ref = db.collection("remarks").add(remark)
    logging.info(
        "Added document remarks/%s at %s", ref.id, now.strftime("%Y-%m-%d %H:%M:%S")
    )
    return ref.id


if __name__ == "__main__":
    # This is used when running locally. Gunicorn is used to run the
    # application on Cloud Run. See entrypoint in Dockerfile.
    app.run(host="localhost", port=int(os.environ.get("PORT", 8080)), debug=True)
