# logging_config.py
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'standard'
        },
        'file_handler': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 3,
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console', 'file_handler'],
        'level': 'DEBUG',
    }
}