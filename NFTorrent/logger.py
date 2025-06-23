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
    },
    "loggers": {
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
