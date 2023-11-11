# SecDuck Upload Server

## Build

```
docker build --tag upload-server .
```

## Run Locally

```
docker run --rm -p 8080:8080 -e PORT=8080 upload-server:latest
```

## Test

```
pytest
```

_Note: you may need to install `pytest` using `pip install pytest`._

## Deploy

```sh
# Set an environment variable with your GCP Project ID
export GOOGLE_CLOUD_PROJECT=<PROJECT_ID>

# Submit a build using Google Cloud Build
gcloud builds submit --tag gcr.io/${GOOGLE_CLOUD_PROJECT}/upload-server

# Deploy to Cloud Run
gcloud run deploy secduck-upload-server --image gcr.io/${GOOGLE_CLOUD_PROJECT}/upload-server
```
