import multiprocessing
import os

bind            = "0.0.0.0:" + os.environ.get("PORT", "8000")
workers         = int(os.environ.get("GUNICORN_WORKERS", min(multiprocessing.cpu_count() + 1, 3)))
worker_class    = "uvicorn.workers.UvicornWorker"
threads         = 4

# Long timeouts so uploads / bulk-generation never cut off mid-request
timeout         = 600
graceful_timeout = 60
keepalive       = 10

accesslog       = "-"
errorlog        = "-"
loglevel        = "warning"

preload_app     = True

# Recycle workers periodically to avoid memory creep
max_requests         = 5000
max_requests_jitter  = 500

# Use tmpfs for heartbeat files — avoids disk I/O stalls
worker_tmp_dir  = "/dev/shm"
