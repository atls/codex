"""Desktop hook and queue command entrypoint."""

from model_fit.entrypoints.hooks.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
