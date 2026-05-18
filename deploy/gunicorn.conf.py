# Gunicorn konfiguratsiyasi — school_attendace_v1
# Ishga tushirish: gunicorn -c deploy/gunicorn.conf.py config.wsgi:application

import multiprocessing

# ── Server ────────────────────────────────────────────────────────────────────
bind = "127.0.0.1:8000"
workers = 2                          # CPU core soni kam bo'lsa 2 yetarli (InsightFace RAM sarflaydi)
worker_class = "sync"                # sync — InsightFace thread-safe emas, gevent xavfli
threads = 1
timeout = 120                        # AI jarayonlar uzoq ketishi mumkin
graceful_timeout = 30
keepalive = 5

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
loglevel = "info"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sus'

# ── Process ───────────────────────────────────────────────────────────────────
proc_name = "school_attendance"
pidfile = "/tmp/school_attendance.pid"
