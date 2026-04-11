import asyncio
from bot.handlers import build_application


def main() -> None:
    app = build_application()
    app.run_polling()


if __name__ == "__main__":
    main()
