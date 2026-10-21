FROM python:3.12-slim
# ffmpeg converts the videos browsers cannot play (mkv, avi, …) on the fly
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# tests ship in the image so `make test` needs nothing on the host
COPY pytest.ini ./
COPY tests ./tests
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
