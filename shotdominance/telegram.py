"""Two-way Telegram. Sending alerts, and reading replies via getUpdates.

getUpdates is a single-consumer long-poll offset cursor - do NOT run two copies
of the bot against the same token, or they will steal each other's updates.
"""
import requests

from . import config


class Telegram:
    def __init__(self, token=None, chat=None):
        self.token = token if token is not None else config.TELEGRAM_BOT_TOKEN
        self.chat = chat if chat is not None else config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat)

    def call(self, method, **payload):
        if not self.enabled:
            return None
        try:
            r = requests.post(
                "https://api.telegram.org/bot%s/%s" % (self.token, method),
                json=payload, timeout=20)
            return r.json()
        except Exception as e:
            print("  ! telegram %s failed: %s" % (method, e), flush=True)
            return None

    def send(self, text):
        """Send a message; returns its message_id (or None). When not
        configured, prints to the console so a dry run is still legible."""
        if not self.enabled:
            print("[telegram not configured]\n" + text, flush=True)
            return None
        body = self.call("sendMessage", chat_id=self.chat, text=text)
        return (((body or {}).get("result")) or {}).get("message_id")

    def updates(self, offset):
        """New updates since `offset`. timeout=0 -> non-blocking short poll."""
        body = self.call("getUpdates", offset=offset + 1, timeout=0)
        return (body or {}).get("result") or []
