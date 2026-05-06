from __future__ import annotations

import argparse

from icesee_hpc_connector.connector_core import DEFAULT_RELAY, run_connector


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ws-url", default=None)
    parser.add_argument("--relay", default=DEFAULT_RELAY)
    parser.add_argument("--session", default=None)
    parser.add_argument("--no-poll", action="store_true")
    args = parser.parse_args()

    run_connector(
        relay=args.relay,
        session=args.session,
        ws_url=args.ws_url,
        poll=not args.no_poll,
    )