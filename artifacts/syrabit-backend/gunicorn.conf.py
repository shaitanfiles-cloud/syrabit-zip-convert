import multiprocessing
import os

bind            = "0.0.0.0:" + os.environ.get("PORT", "8000")
_default_workers = min(multiprocessing.cpu_count(), 2)
workers         = int(os.environ.get("GUNICORN_WORKERS", str(_default_workers)))
worker_class    = "uvicorn.workers.UvicornWorker"
threads         = int(os.environ.get("GUNICORN_THREADS", "2"))

timeout         = 300
graceful_timeout = 60
keepalive       = 30

accesslog       = "-"
errorlog        = "-"
loglevel        = os.environ.get("LOG_LEVEL", "warning")

preload_app     = True

max_requests         = 5000
max_requests_jitter  = 500

worker_tmp_dir  = "/dev/shm"
