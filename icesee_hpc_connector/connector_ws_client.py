from __future__ import annotations

import argparse
import os

from icesee_hpc_connector.connector_core import DEFAULT_RELAY, run_connector


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay", default=DEFAULT_RELAY)
    parser.add_argument(
        "--pairing-code",
        default=os.environ.get("CRYOSTACK_PAIRING_CODE") or None,
        help="one-time pairing code from the Connector Setup page",
    )
    parser.add_argument("--session", default=None, help="session id (requires --session-secret)")
    parser.add_argument("--session-secret", default=None, help="session secret (dev/testing)")
    parser.add_argument("--ws-url", default=None)
    parser.add_argument("--no-poll", action="store_true")
    args = parser.parse_args()

    run_connector(
        relay=args.relay,
        pairing_code=args.pairing_code,
        session=args.session,
        session_secret=args.session_secret,
        ws_url=args.ws_url,
        poll=not args.no_poll,
    )
