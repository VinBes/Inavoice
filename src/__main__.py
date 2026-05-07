import logging

import structlog

import config
from bot.handlers import build_application
from health import start_health_server


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )


def main() -> None:
    configure_logging()
    start_health_server(config.HEALTH_PORT)
    app = build_application()
    app.run_polling()


if __name__ == "__main__":
    main()
