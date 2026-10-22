"""Route uncaught Python exceptions through the application logger."""

import sys
import threading
from logging import Logger


def install_exception_hooks(logger: Logger) -> None:
    def handle_main_exception(exc_type, exc_value, exc_traceback):
        logger.critical(
            "Uncaught exception in main thread",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def handle_thread_exception(args: threading.ExceptHookArgs):
        logger.critical(
            "Uncaught exception in thread %s",
            args.thread.name if args.thread is not None else "<unknown>",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_main_exception
    threading.excepthook = handle_thread_exception
