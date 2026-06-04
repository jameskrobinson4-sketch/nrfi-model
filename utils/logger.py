import logging

def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(name)

def set_global_level(level: int) -> None:
    logging.getLogger().setLevel(level)
