import asyncio
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


async def _start_health_with_loop(app) -> None:
    """post_init hook: capture the running loop, then launch the HTTP server.

    The webhook handler runs on a daemon thread, but the bot.send_message and
    DB calls are async — we hop back onto this loop via run_coroutine_threadsafe.
    """
    loop = asyncio.get_running_loop()
    start_health_server(config.HEALTH_PORT, bot=app.bot, loop=loop)


def main() -> None:
    configure_logging()
    app = build_application(extra_post_init=_start_health_with_loop)
    app.run_polling()


if __name__ == "__main__":
    main()
