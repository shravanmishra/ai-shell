"""`ai-shell` command-line entry point.

    ai-shell                       open the interactive shell (default)
    ai-shell "list files over 1gb" translate + confirm + run one request
    ai-shell -p "delete node_modules everywhere"   print only, do not run
"""

import argparse
import os
import sys

from . import __version__


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="ai-shell",
        description="Translate natural language into a shell command, confirm, "
                    "and run it -- powered by a local LLM.",
    )
    parser.add_argument(
        "request", nargs="*",
        help="one-shot: translate this request instead of opening the shell",
    )
    parser.add_argument(
        "-p", "--print", dest="print_only", action="store_true",
        help="print the generated command and exit; do not run it",
    )
    parser.add_argument(
        "-m", "--model", metavar="REPO_ID",
        help="override the Hugging Face model repo id for this run",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.model:
        os.environ["SHELLAI_MODEL_REPO"] = args.model

    # Import deferred so `--help` / `--version` never touch the model stack.
    from . import app

    if not args.request:
        app.main()  # <-- plain `ai-shell` opens the interactive REPL
        return

    query = " ".join(args.request)
    app.ensure_logging()
    if args.print_only:
        app.get_local_model()
        try:
            print(app.get_shell_command(query))
        except Exception as exc:  # noqa: BLE001 - surface a clean message
            sys.exit(f"ai-shell: {exc}")
    else:
        app.load_history()
        app.get_local_model()
        app.handle_query(query)


if __name__ == "__main__":
    main()
