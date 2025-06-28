config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(levelname)-4.4s - %(name)-30.30s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "taskQueueFile": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "./log/nftorrent-task.log",
            "formatter": "default",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
        },
    },
    "loggers": {
        "NFTorrent.TaskQueue": {
            "handlers": ["taskQueueFile"],
            "level": "INFO",
            "propagate": False,
        },
        # "NFTorrent.indexer": {
        #     "handlers": ["console"],
        #     "level": "INFO",
        #     "propagate": False,
        # },
        # 'pytonlib': {
        #     'handlers': ['console'],
        #     'level': 'INFO',
        #     'propagate': False,
        # },
        # 'NFTorrent.tonlib': {
        #     'handlers': ['console'],
        #     'level': 'INFO',
        #     'propagate': False,
        # },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}
