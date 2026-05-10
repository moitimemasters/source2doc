import uvicorn

from app.config import get_config


def main() -> None:
    config = get_config()
    uvicorn.run(
        "app.app:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
    )


if __name__ == "__main__":
    main()
