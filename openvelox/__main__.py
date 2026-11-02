import multiprocessing
import sys

from openvelox.app import main
from openvelox.crashlog import install, safe_print

if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        install()
    except Exception as exc:  # noqa: BLE001
        safe_print(f"OpenVelox failed to install crash logging: {exc}")
    raise SystemExit(main())
