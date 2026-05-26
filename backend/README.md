The project was developed as a prototype of a CTG monitoring system. It combines signal processing, real-time stream emulation, report generation, and a neural network model for fetal hypoxia risk prediction.

# CTG Monitoring API

A FastAPI service that simulates a CTG monitor for fetal heart rate and uterine activity analysis. It supports streaming data points and periodic annotations, which makes it useful for demos, testing, and integration with a frontend client.

## Contents

- [Overview](#overview)
- [Project structure](#project-structure)
- [Setup and run](#setup-and-run)
- [API endpoints](#api-endpoints)
- [Request examples](#request-examples)
- [CSV format](#csv-format)

## Overview

The service accepts CSV files with two CTG channels:

- fetal heart rate (`fhr`)
- uterine activity (`uterus`)

It can emulate real-time monitoring:

- data points are sent in `moments_batch` events every `interval_sec` seconds
- annotations are produced every 30 seconds of simulated time
- clients can subscribe to the stream using Server-Sent Events (SSE)

## Project structure

```text
.
├── api_server.py         # FastAPI application
├── processing.py         # Signal processing logic and rule-based algorithms
├── requirements.txt      # Python dependencies
├── training/             # Model training code and documentation
├── Dockerfile            # Docker image definition
├── report_generator.py   # CTG report generation utility
├── hypoxia_predictor.py  # PyTorch model initialization and inference helper
├── best_fold0.pt         # TinyTCN checkpoint (base=64)
├── example/              # Sample CSV files for testing
├── docker-compose.yml    # Docker Compose configuration
└── README.md             # Project documentation
```

## Setup and run

### 1. Clone the repository

```bash
git clone https://github.com/Makual/course_project_3rd.git
cd course_project_3rd/backend
```

### 2. Run with Docker Compose

```bash
docker compose up --build -d
```

### 3. Check that the service is running

The API should be available at:

```text
http://localhost:8000
```

Swagger documentation:

```text
http://localhost:8000/docs
```

## API endpoints

### `GET /`

Returns basic service information and a list of available endpoints.

### `POST /api/upload`

Uploads two CSV files, `fhr_file` and `uterus_file`, and starts a monitoring session.

The response contains a `monitor_id` and a stream URL.

### `GET /api/stream/{monitor_id}`

Subscribes to the monitoring stream for a specific monitor.

The stream uses SSE and sends data points together with periodic annotations.

### `GET /api/monitors`

Returns active and finished monitor sessions.

### `POST /api/instant`

Processes the uploaded data immediately without starting a stream.

The response contains the full list of `moments` and one complete `annotation`.

### `POST /api/monitors/{monitor_id}/report`

Returns a CTG report for a finished monitoring session.

## Request examples

### Upload data and start streaming

```bash
curl -X POST "http://localhost:8000/api/upload" \
  -F "fhr_file=@fhr.csv" \
  -F "uterus_file=@uterus.csv"
```

Example response:

```json
{
  "monitor_id": "a1b2c3d4-...",
  "points": 1500,
  "interval_sec": 1.0,
  "speed": 1.0,
  "annotation_period_model_sec": 30.0,
  "stream_url": "/api/stream/a1b2c3d4-..."
}
```

### Connect to the stream

```bash
curl -N http://localhost:8000/api/stream/a1b2c3d4-...
```

### Run instant processing

```bash
curl -X POST "http://localhost:8000/api/instant" \
  -F "fhr_file=@example/full_bpm.csv" \
  -F "uterus_file=@example/full_uterus.csv"
```

## CSV format

The input CSV can use one of the following formats.

### Single-column CSV

```csv
value
123
124
122
```

### Two-column CSV

```csv
time_sec,value
0.0,123
0.5,124
1.0,122
```
