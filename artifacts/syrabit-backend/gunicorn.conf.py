import multiprocessing
import os

bind            = "0.0.0.0:" + os.environ.get("BACKEND_PORT", os.environ.get("PORT", "7766"))
workers         = int(os.environ.get("GUNICORN_WORKERS", "3"))
worker_class    = "uvicorn.workers.UvicornWorker"
threads         = int(os.environ.get("GUNICORN_THREADS", "4"))

timeout         = 300
graceful_timeout = 60
keepalive       = 30

accesslog       = "-"
errorlog        = "-"
loglevel        = os.environ.get("LOG_LEVEL", "warning")

preload_app     = True

max_requests         = 5000
max_requests_jitter  = 500

worker_tmp_dir  = "/dev/shm" if os.path.isdir("/dev/shm") else None
