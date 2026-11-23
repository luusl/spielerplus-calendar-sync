"""Headless Google login for containers.

`calendar-sync google-login` opens a local browser, which a container doesn't have.
This wrapper swaps only that step for a copy/paste flow and then runs the tool's own
`google-login` command, so scopes, token format and token paths stay exactly as the
tool defines them (including every job in jobs.toml).

  1. A Google login link is printed.            -> open it in ANY browser (your PC/phone)
  2. Sign in and approve.
  3. The browser then shows "can't connect to localhost" - that is expected.
  4. Copy the full URL from the address bar and paste it here.
"""
import os
import sys

# The redirect target is http://localhost (nothing listens there); oauthlib must accept it.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

REDIRECT_URI = "http://localhost:8080/"


def _paste_flow(self, **_ignored):
    self.redirect_uri = REDIRECT_URI
    url, _state = self.authorization_url(access_type="offline", prompt="consent")
    print("\n1) Open this link in a browser and sign in with the Google account that owns the calendar:\n")
    print(url)
    print(
        "\n2) After approving, the browser will show an error page ('localhost refused to connect').\n"
        "   That is expected. Copy the FULL address from the address bar and paste it below.\n"
    )
    try:
        answer = input("Paste URL here: ").strip()
    except EOFError:
        sys.exit("No input available - run with a terminal: docker compose run --rm calendar-sync google-login")
    if answer.startswith("http"):
        self.fetch_token(authorization_response=answer)
    else:  # allow pasting just the code=... value
        self.fetch_token(code=answer)
    return self.credentials


InstalledAppFlow.run_local_server = _paste_flow

from calendar_sync.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["google-login", *sys.argv[1:]]))
