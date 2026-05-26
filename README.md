# Kuznetsov Maxim Data science and business analytics 233

# Project Structure

The project is split into two independent parts:

- `backend/` — server-side code, model training scripts, and signal processing algorithms.
- `frontend/` — client-side application.

Each folder contains its own `Dockerfile` and dependency files. The backend and frontend should be built and deployed separately.

```bash
git clone https://github.com/Makual/course_project_3rd.git
cd course_project_3rd/backend/backend
docker compose up --build -d
```

```bash
cd ../frontend
echo "NEXT_PUBLIC_BACKEND_URL=http://localhost:8000" > .env
docker compose up --build -d
```
