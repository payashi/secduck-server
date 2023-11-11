#!/usr/bin/env python

import json
import base64
import wave


import os

from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/", methods=["POST"])
def index():
    """JSON test"""
    data = request.get_json()
    print(jsonify(data))
    return f"Server: Got {data['user_id']}"


if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 8080))

    # This is used when running locally. Gunicorn is used to run the
    # application on Cloud Run. See entrypoint in Dockerfile.
    app.run(host="localhost", port=PORT, debug=True)
