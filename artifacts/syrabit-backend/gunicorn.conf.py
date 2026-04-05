import multiprocessing
import os

bind            = "0.0.0.0:" + os.environ.get("PORT", "8000")
workers         = int(os.environ.get("GUNICORN_WORKERS", min(multiprocessing.cpu_count() + 1, 4)))
worker_class    = "uvicorn.workers.UvicornWorker"
threads         = 4

timeout         = 300
graceful_timeout = 60
keepalive       = 30

accesslog       = "-"
errorlog        = "-"
loglevel        = "warning"

preload_app     = True

max_requests         = 5000
max_requests_jitter  = 500

worker_tmp_dir  = "/dev/shm"
