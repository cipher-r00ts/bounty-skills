#!/usr/bin/env python3
"""mailbox.py — read-only Gmail mailbox helper for signup verification.

Purpose: let the agent finish a registration flow without a human: create a
per-target alias, wait for the verification mail, pull the OTP or the
confirmation link, and continue.

Two backends, chosen from the stored config:
  * Gmail API with an OAuth refresh token (gmail.readonly) — preferred
  * IMAP with a Gmail App Password — fallback

Nothing is ever sent from this account and nothing is marked as read (IMAP uses
BODY.PEEK; the Gmail API get call does not modify labels).

Credentials are resolved in this order:
  1. --config PATH
  2. $GMAIL_CONFIG
  3. ~/.claude/config/secrets.json   (key: gmail)
  4. ~/.config/opencode/secrets.json (key: gmail)
  5. $GMAIL_ADDRESS / $GMAIL_APP_PASSWORD

Never print the password. See setup.sh to store it with mode 0600.

Examples:
  mailbox.py check
  mailbox.py alias --tag 3hk --json
  mailbox.py wait --to 'me+3hk-a1b2c3@gmail.com' --timeout 180 --json
  mailbox.py otp  --to 'me+3hk-a1b2c3@gmail.com' --wait 120 --subject-re 'verif|code'
  mailbox.py link --to 'me+3hk-a1b2c3@gmail.com' --wait 120 --domain three.com.hk
  mailbox.py list --to 'me+3hk-a1b2c3@gmail.com' --json
  mailbox.py selftest
"""

from __future__ import annotations

import argparse
import base64
import binascii
import email
import imaplib
import json
import math
import os
import re
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message as EmailMessage
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_IMAP_HOST = "imap.gmail.com"
DEFAULT_IMAP_PORT = 993
DEFAULT_CONFIGS = (
    "~/.claude/config/secrets.json",
    "~/.config/opencode/secrets.json",
)
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

CODE_KEYWORDS = re.compile(
    r"(?i)(code|otp|one[\s-]?time|passcode|pin|verification|verify|confirm|"
    r"activate|token|challenge)"
)
LINK_POSITIVE = (
    "verify", "verif", "confirm", "activate", "validate", "registration",
    "signup", "sign-up", "register", "email", "account", "token", "magic",
    "onboard", "invite", "auth",
)
LINK_NEGATIVE = (
    "unsubscribe", "preferences", "privacy", "terms", "help", "support",
    "contact", "track", "pixel", "utm_", "open?", "feedback", "survey",
)
SAFE_LINK_SCHEMES = ("http", "https")
IMAGE_SUFFIX = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js|woff2?)(\?|$)", re.I)


class MailboxError(RuntimeError):
    """A configuration, connection or authentication problem."""


# --------------------------------------------------------------------------
# credentials


@dataclass
class Account:
    address: str
    password: str | None = None
    host: str = DEFAULT_IMAP_HOST
    port: int = DEFAULT_IMAP_PORT
    oauth: dict | None = None
    preferred_backend: str | None = None

    @property
    def backend(self) -> str:
        if self.preferred_backend == "imap":
            return "imap"
        if self.preferred_backend == "gmail-api":
            return "gmail-api"
        if self.oauth and self.oauth.get("refresh_token"):
            return "gmail-api"
        return "imap"


def _load_json(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.is_file():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def resolve_account(args, *, require_password: bool = True) -> Account:
    data: dict = {}
    candidates = []
    if getattr(args, "config", None):
        candidates.append(args.config)
    if os.environ.get("GMAIL_CONFIG"):
        candidates.append(os.environ["GMAIL_CONFIG"])
    candidates.extend(DEFAULT_CONFIGS)

    for candidate in candidates:
        raw = _load_json(candidate)
        gmail = raw.get("gmail")
        if isinstance(gmail, dict) and (
            gmail.get("address") or gmail.get("app_password") or gmail.get("oauth")
        ):
            data = gmail
            break

    address = (
        getattr(args, "address", None)
        or os.environ.get("GMAIL_ADDRESS")
        or data.get("address")
        or ""
    ).strip()
    password = (
        os.environ.get("GMAIL_APP_PASSWORD")
        or data.get("app_password")
        or data.get("appPassword")
        or data.get("password")
        or ""
    )
    password = re.sub(r"\s+", "", str(password))
    host = getattr(args, "host", None) or data.get("imap_host") or DEFAULT_IMAP_HOST
    port = int(getattr(args, "port", None) or data.get("imap_port") or DEFAULT_IMAP_PORT)

    oauth = data.get("oauth")
    if not isinstance(oauth, dict):
        oauth = None
    if os.environ.get("GMAIL_OAUTH_REFRESH_TOKEN"):
        oauth = dict(oauth or {})
        oauth["refresh_token"] = os.environ["GMAIL_OAUTH_REFRESH_TOKEN"]
        oauth["client_id"] = os.environ.get("GMAIL_OAUTH_CLIENT_ID", oauth.get("client_id", ""))
        oauth["client_secret"] = os.environ.get(
            "GMAIL_OAUTH_CLIENT_SECRET", oauth.get("client_secret", "")
        )

    has_oauth = bool(oauth and oauth.get("refresh_token"))
    backend_hint = str(data.get("backend") or "").strip().lower()
    if backend_hint in {"oauth", "gmail", "gmail-api", "api"}:
        backend_hint = "gmail-api"
    elif backend_hint != "imap":
        backend_hint = None

    if not address:
        raise MailboxError(
            "no Gmail address configured. Run "
            ".opencode/skills/registration/scripts/oauth_setup.py (Gmail API) or "
            "setup.sh (IMAP app password)."
        )
    if backend_hint == "gmail-api" and not has_oauth:
        raise MailboxError(
            "config selects the Gmail API backend but has no OAuth refresh token; "
            "run oauth_setup.py or remove the backend override."
        )
    if backend_hint == "imap" and not password:
        raise MailboxError(
            "config selects the IMAP backend but has no app password; "
            "run setup.sh or remove the backend override."
        )
    if require_password and not password and not has_oauth:
        raise MailboxError(
            "no credentials configured. Run oauth_setup.py for the read-only Gmail "
            "API, or setup.sh for an IMAP App Password."
        )
    return Account(
        address=address,
        password=password or None,
        host=host.strip(),
        port=port,
        oauth=oauth,
        preferred_backend=backend_hint,
    )


def auth_hint(message: str) -> str:
    low = message.lower()
    if "application-specific password" in low or "invalid credentials" in low:
        return (
            "Gmail rejected the login. IMAP requires a 16-character App Password: "
            "Google Account > Security > 2-Step Verification > App passwords. "
            "A normal account password will not work, and 2-Step Verification "
            "must already be enabled."
        )
    if "web login required" in low:
        return (
            "Gmail requires a browser login for this account. Open Gmail once in a "
            "browser, complete any challenge, then retry with an App Password."
        )
    return message


# --------------------------------------------------------------------------
# message model and parsing


@dataclass
class Message:
    uid: str
    mailbox: str
    subject: str
    sender: str
    date: datetime | None
    text: str
    html: str
    message_id: str = ""

    def age_seconds(self, now: datetime) -> float | None:
        if self.date is None:
            return None
        return (now - self.date).total_seconds()


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def decode_payload(part: EmailMessage) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    if isinstance(payload, str):
        return payload
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, "replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", "replace")


class _HTMLScan(HTMLParser):
    """Extract visible text and href values from an HTML mail body."""

    SKIP = {"script", "style", "head", "title"}
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hrefs: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value:
                    self.hrefs.append(value)
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLScan()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    text = "".join(parser.parts)
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def html_hrefs(html: str) -> list[str]:
    parser = _HTMLScan()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []
    return parser.hrefs


def body_parts(msg: EmailMessage) -> tuple[str, str]:
    texts: list[str] = []
    htmls: list[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            texts.append(decode_payload(part))
        elif ctype == "text/html":
            htmls.append(decode_payload(part))
    text = "\n".join(t for t in texts if t.strip())
    html = "\n".join(htmls)
    if not text and html:
        text = html_to_text(html)
    return text, html


def parse_message(raw: bytes, uid: str, mailbox: str) -> Message:
    msg = email.message_from_bytes(raw)
    text, html = body_parts(msg)
    date: datetime | None = None
    raw_date = msg.get("Date")
    if raw_date:
        try:
            date = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError, OverflowError):
            date = None
    if date is not None and date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return Message(
        uid=str(uid),
        mailbox=mailbox,
        subject=decode_mime_header(msg.get("Subject")).strip(),
        sender=decode_mime_header(msg.get("From")).strip(),
        date=date,
        text=text,
        html=html,
        message_id=(msg.get("Message-ID") or "").strip(),
    )


# --------------------------------------------------------------------------
# extraction heuristics


def extract_codes(subject: str, text: str) -> list[dict]:
    """Rank numeric and alphanumeric one-time codes. Subject wins ties."""
    corpus = f"{subject}\n{text}"
    cutoff = len(subject) + 1
    found: dict[str, dict] = {}

    def add(code: str, score: int, start: int, end: int) -> None:
        key = code.upper()
        if key not in found or found[key]["score"] < score:
            window = corpus[max(0, start - 70): min(len(corpus), end + 70)]
            found[key] = {
                "code": code,
                "score": score,
                "context": re.sub(r"\s+", " ", window).strip()[:160],
            }

    for match in re.finditer(r"(?<![\w-])(\d{4,8})(?![\w-])", corpus):
        code = match.group(1)
        if len(code) == 4 and 2020 <= int(code) <= 2035:
            continue  # a year, not a code
        score = {6: 6, 4: 4, 8: 3}.get(len(code), 2)
        window = corpus[max(0, match.start() - 70): match.end() + 70]
        if CODE_KEYWORDS.search(window):
            score += 5
        if match.start() < cutoff:
            score += 3
        if re.search(
            r"(?i)(code|otp|pin)[^\d]{0,24}$",
            corpus[max(0, match.start() - 40): match.start()],
        ):
            score += 2
        add(code, score, match.start(), match.end())

    for match in re.finditer(r"(?<![\w-])([A-Za-z0-9]{5,10})(?![\w-])", corpus):
        token = match.group(1)
        if not (re.search(r"[A-Za-z]", token) and re.search(r"\d", token)):
            continue
        if token.lower() in {"gmail", "https", "http", "smtp", "imap", "utf8"}:
            continue
        window = corpus[max(0, match.start() - 70): match.end() + 70]
        if not CODE_KEYWORDS.search(window):
            continue
        score = 4
        if match.start() < cutoff:
            score += 2
        add(token, score, match.start(), match.end())

    ranked = sorted(found.values(), key=lambda item: (-item["score"], -len(item["code"])))
    return ranked[:5]


def unwrap_url(url: str) -> str:
    """Unwrap the usual corporate mail-gateway redirectors."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    host = parsed.netloc.lower().split(":")[0]
    query = parse_qs(parsed.query)
    if host.endswith("safelinks.protection.outlook.com") and query.get("url"):
        return unquote(query["url"][0])
    if host in {"www.google.com", "google.com"} and parsed.path == "/url" and query.get("q"):
        return unquote(query["q"][0])
    if host.endswith("linkedin.com") and parsed.path.startswith("/e/") and query.get("url"):
        return unquote(query["url"][0])
    return url


def clean_url(url: str) -> str:
    url = unescape(url).strip().strip("<>\"'")
    url = unwrap_url(url)
    return url.rstrip(".,;:!?)]}\u201d\u2019")


def score_link(url: str, domain: str | None = None) -> int:
    try:
        parsed = urlparse(url)
    except ValueError:
        return -99
    if parsed.scheme.lower() not in SAFE_LINK_SCHEMES or not parsed.netloc:
        return -99
    host = parsed.netloc.lower().split(":")[0]
    target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
    lowered = target.lower()
    score = 1 if parsed.scheme == "https" else 0
    if domain:
        wanted = domain.lower().strip(".")
        if host == wanted or host.endswith("." + wanted):
            score += 8
    for keyword in LINK_POSITIVE:
        if keyword in lowered:
            score += 3
    for keyword in LINK_NEGATIVE:
        if keyword in lowered:
            score -= 7
    if re.search(r"[?&](token|code|key|t|u|id|hash)=", lowered):
        score += 3
    if re.search(r"[a-z0-9]{20,}", lowered):
        score += 2
    if IMAGE_SUFFIX.search(lowered):
        score -= 9
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        score -= 6
    if len(lowered) > 60:
        score += 1
    if parsed.fragment and len(parsed.fragment) > 8:
        score += 1
    return score


def extract_links(message: Message, domain: str | None = None) -> list[dict]:
    candidates: list[str] = []
    candidates.extend(html_hrefs(message.html))
    candidates.extend(re.findall(r"https?://[^\s<>\"')]+", message.text))
    candidates.extend(re.findall(r"https?://[^\s<>\"')]+", message.html))

    seen: set[str] = set()
    ranked: list[dict] = []
    for raw in candidates:
        url = clean_url(raw)
        if url in seen or not url:
            continue
        seen.add(url)
        score = score_link(url, domain)
        if score < 0:
            continue
        ranked.append({"url": url, "score": score})
    ranked.sort(key=lambda item: -item["score"])
    return ranked[:8]


def excerpt(text: str, limit: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[:limit]


# --------------------------------------------------------------------------
# IMAP client


class ImapMailbox:
    def __init__(self, account: Account) -> None:
        self.account = account
        self.imap: imaplib.IMAP4_SSL | None = None
        self.is_gmail = False
        self.backend = "imap"

    def __enter__(self) -> "ImapMailbox":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        context = ssl.create_default_context()
        try:
            self.imap = imaplib.IMAP4_SSL(
                self.account.host,
                self.account.port,
                ssl_context=context,
                timeout=30,
            )
        except (OSError, ssl.SSLError) as exc:
            raise MailboxError(
                f"cannot reach {self.account.host}:{self.account.port}: {exc}"
            ) from exc
        try:
            self.imap.login(self.account.address, self.account.password or "")
        except imaplib.IMAP4.error as exc:
            raise MailboxError(auth_hint(str(exc))) from exc
        self.is_gmail = "X-GM-EXT-1" in {cap.upper() for cap in self.imap.capabilities}

    def close(self) -> None:
        if not self.imap:
            return
        try:
            self.imap.close()
        except Exception:
            pass
        try:
            self.imap.logout()
        except Exception:
            pass
        self.imap = None

    def special_mailbox(self, flag: str, fallback: str) -> str:
        assert self.imap
        try:
            _typ, rows = self.imap.list()
        except imaplib.IMAP4.error:
            return fallback
        for row in rows or []:
            if isinstance(row, bytes):
                text = row.decode("utf-8", "replace")
            else:
                text = str(row)
            if not re.search(rf"\\{flag}\b", text, re.I):
                continue
            match = re.search(r'"((?:[^"\\]|\\.)*)"\s*$', text)
            if match:
                return match.group(1).replace('\\"', '"')
        return fallback

    def select(self, mailbox: str) -> bool:
        assert self.imap
        try:
            typ, _data = self.imap.select(f'"{mailbox}"', readonly=True)
        except imaplib.IMAP4.error:
            return False
        return typ == "OK"

    def search_uids(self, *criteria: str) -> list[int]:
        assert self.imap
        try:
            typ, data = self.imap.uid("SEARCH", None, *criteria)
        except imaplib.IMAP4.error as exc:
            raise MailboxError(f"IMAP search failed: {exc}") from exc
        if typ != "OK":
            raise MailboxError(f"IMAP search failed: {data!r}")
        payload = data[0] if data else b""
        if isinstance(payload, str):
            payload = payload.encode()
        return [int(value) for value in (payload or b"").split() if value.isdigit()]

    def fetch(self, uid: int, mailbox: str) -> Message | None:
        assert self.imap
        typ, data = self.imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if typ != "OK":
            return None
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                return parse_message(item[1], str(uid), mailbox)
        return None

    def boxes(self, include_spam: bool) -> list[str]:
        if not self.is_gmail:
            return ["INBOX"]
        boxes = [self.special_mailbox("All", "[Gmail]/All Mail")]
        if include_spam:
            boxes.append(self.special_mailbox("Spam", "[Gmail]/Spam"))
        return boxes

    def search(
        self,
        alias: str | None,
        *,
        days: int = 2,
        limit: int = 20,
        include_spam: bool = True,
    ) -> list[Message]:
        days = max(1, int(days))
        results: list[Message] = []
        seen: set[str] = set()

        for box in self.boxes(include_spam):
            if not self.select(box):
                continue
            if self.is_gmail:
                query = "newer_than:%dd" % days
                if alias:
                    query = f"(to:{alias} OR deliveredto:{alias}) {query}"
                uids = self.search_uids("X-GM-RAW", f'"{query}"')
            else:
                since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
                if alias:
                    uids = self.search_uids("TO", f'"{alias}"', "SINCE", since)
                else:
                    uids = self.search_uids("SINCE", since)

            for uid in sorted(uids, reverse=True)[:limit]:
                message = self.fetch(uid, box)
                if message is None:
                    continue
                key = message.message_id or f"{message.subject}|{message.sender}|{message.date}"
                if key in seen:
                    continue
                seen.add(key)
                results.append(message)

        results.sort(
            key=lambda message: (
                message.date.timestamp() if message.date else 0,
                int(message.uid) if message.uid.isdigit() else 0,
            ),
            reverse=True,
        )
        return results[:limit]

    def unseen(self) -> int | None:
        if not self.select("INBOX"):
            return None
        try:
            typ, data = self.imap.uid("SEARCH", None, "UNSEEN")  # type: ignore[union-attr]
        except imaplib.IMAP4.error:
            return None
        if typ != "OK":
            return None
        payload = data[0] if data else b""
        if isinstance(payload, str):
            payload = payload.encode()
        return len((payload or b"").split())


# --------------------------------------------------------------------------
# Gmail API client (OAuth refresh token, read-only scope)


class GmailApiMailbox:
    """Read-only Gmail API backend with the same surface as ImapMailbox."""

    def __init__(self, account: Account) -> None:
        self.account = account
        self.oauth = account.oauth or {}
        self.token = ""
        self.expires_at = 0.0
        self.is_gmail = True
        self.backend = "gmail-api"

    def __enter__(self) -> "GmailApiMailbox":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        if not self.oauth.get("refresh_token"):
            raise MailboxError(
                "Gmail API backend has no refresh token. Run oauth_setup.py."
            )
        self._refresh()

    def close(self) -> None:
        self.token = ""

    def _refresh(self) -> None:
        payload = {
            "client_id": self.oauth.get("client_id", ""),
            "refresh_token": self.oauth.get("refresh_token", ""),
            "grant_type": "refresh_token",
        }
        if self.oauth.get("client_secret"):
            payload["client_secret"] = self.oauth["client_secret"]
        data = urllib.parse.urlencode(payload).encode()
        request = urllib.request.Request(
            GMAIL_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                token = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if "invalid_grant" in detail:
                raise MailboxError(
                    "OAuth refresh token is expired or revoked. Google expires "
                    "Testing-mode refresh tokens after 7 days: re-run oauth_setup.py."
                ) from exc
            raise MailboxError(
                f"OAuth token refresh failed ({exc.code}): {detail[:300]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise MailboxError(f"cannot reach Google OAuth: {exc.reason}") from exc

        self.token = token.get("access_token", "")
        self.expires_at = time.time() + float(token.get("expires_in", 3600))
        if not self.token:
            raise MailboxError(f"OAuth token response had no access_token: {token}")

    def _ensure_token(self) -> None:
        if not self.token or time.time() > self.expires_at - 60:
            self._refresh()

    def _api(self, path: str, params: dict | None = None, *, retry: bool = True) -> dict:
        self._ensure_token()
        url = GMAIL_API + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code == 401 and retry:
                self._refresh()
                return self._api(path, params, retry=False)
            raise MailboxError(f"Gmail API {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise MailboxError(f"cannot reach Gmail API: {exc.reason}") from exc

    def profile(self) -> dict:
        return self._api("/profile")

    def select(self, mailbox: str) -> bool:
        return True

    def special_mailbox(self, flag: str, fallback: str) -> str:
        return fallback

    def fetch(self, uid: str, mailbox: str) -> Message | None:
        payload = self._api(f"/messages/{uid}", {"format": "raw"})
        raw = payload.get("raw")
        if not raw:
            return None
        padded = raw + "=" * (-len(raw) % 4)
        try:
            data = base64.urlsafe_b64decode(padded)
        except (ValueError, binascii.Error):
            return None
        return parse_message(data, str(uid), "gmail-api")

    def unseen(self) -> int | None:
        result = self._api("/messages", {"q": "is:unread in:inbox", "maxResults": 1})
        estimate = result.get("resultSizeEstimate")
        return int(estimate) if isinstance(estimate, int) else None

    def search(
        self,
        alias: str | None,
        *,
        days: int = 2,
        limit: int = 20,
        include_spam: bool = True,
    ) -> list[Message]:
        days = max(1, int(days))
        query = f"newer_than:{days}d"
        if alias:
            query = f'to:"{alias}" {query}'
        params = {
            "q": query,
            "maxResults": max(1, min(int(limit), 100)),
            "includeSpamTrash": "true" if include_spam else "false",
        }
        listing = self._api("/messages", params)
        results: list[Message] = []
        seen: set[str] = set()
        for item in listing.get("messages", []) or []:
            message_id = item.get("id")
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            message = self.fetch(str(message_id), "gmail-api")
            if message is not None:
                results.append(message)
        results.sort(
            key=lambda message: message.date.timestamp() if message.date else 0,
            reverse=True,
        )
        return results[:limit]


def open_mailbox(account: Account) -> ImapMailbox | GmailApiMailbox:
    if account.backend == "gmail-api":
        return GmailApiMailbox(account)
    return ImapMailbox(account)


# --------------------------------------------------------------------------
# commands


def parse_since(value: str) -> timedelta:
    match = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", value or "", re.I)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        return timedelta(minutes=amount) if unit == "m" else (
            timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
        )
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MailboxError(f"bad --since value: {value!r} (use 15m, 2h, 1d or ISO-8601)") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - stamp
    return delta if delta.total_seconds() > 0 else timedelta(seconds=1)


def keep(message: Message, cutoff: datetime, subject_re: str | None, from_re: str | None) -> bool:
    if message.date is not None and message.date < cutoff:
        return False
    if subject_re and not re.search(subject_re, message.subject, re.I):
        return False
    if from_re and not re.search(from_re, message.sender, re.I):
        return False
    return True


def wait_for_message(
    mailbox: ImapMailbox,
    alias: str | None,
    *,
    since: timedelta,
    timeout: int,
    interval: float,
    limit: int,
    subject_re: str | None,
    from_re: str | None,
    include_spam: bool,
) -> Message | None:
    cutoff = datetime.now(timezone.utc) - since
    days = max(1, math.ceil(since.total_seconds() / 86400) + 1)
    deadline = time.monotonic() + max(0, timeout)
    while True:
        messages = mailbox.search(alias, days=days, limit=limit, include_spam=include_spam)
        for message in messages:
            if keep(message, cutoff, subject_re, from_re):
                return message
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(interval, remaining))


def message_dict(message: Message, *, domain: str | None = None) -> dict:
    codes = extract_codes(message.subject, message.text)
    links = extract_links(message, domain)
    return {
        "ok": True,
        "uid": message.uid,
        "mailbox": message.mailbox,
        "subject": message.subject,
        "from": message.sender,
        "date": message.date.isoformat() if message.date else None,
        "codes": codes,
        "links": links,
        "excerpt": excerpt(message.text),
    }


def print_json(value: dict | list) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def print_message(message: Message, *, domain: str | None = None) -> None:
    payload = message_dict(message, domain=domain)
    print(f"Subject : {payload['subject']}")
    print(f"From    : {payload['from']}")
    print(f"Date    : {payload['date']}")
    print(f"Box/UID : {payload['mailbox']} / {payload['uid']}")
    if payload["codes"]:
        best = payload["codes"][0]
        print(f"Code    : {best['code']}   (score {best['score']})")
        for candidate in payload["codes"][1:]:
            print(f"  alt   : {candidate['code']}   (score {candidate['score']})")
    if payload["links"]:
        print("Links   :")
        for link in payload["links"][:5]:
            print(f"  [{link['score']:>2}] {link['url']}")
    print(f"Excerpt : {payload['excerpt'][:300]}")


# --------------------------------------------------------------------------
# selftest


SELFTEST_MESSAGES = [
    (
        "Your verification code is 482913",
        "Example <no-reply@example.com>",
        "Use code 482913 to finish signing in. It expires in 10 minutes.\n"
        "Or continue: https://app.example.com/verify?token=abc123def456ghi789jkl\n"
        "Unsubscribe: https://app.example.com/preferences?utm_source=mail",
    ),
    (
        "Confirm your email address",
        "Example <hello@example.com>",
        "Welcome! <a href=\"https://www.example.com/account/confirm?token=Zx9Yw8Vu7Ts6Rq5Po4\">"
        "Confirm email</a><img src=\"https://cdn.example.com/pixel.gif\" width=\"1\">",
    ),
    (
        "Your one-time passcode",
        "Example <security@example.com>",
        "Your OTP is K7X9P2. Do not share it.",
    ),
]


def build_selftest_message(index: int) -> Message:
    subject, sender, body = SELFTEST_MESSAGES[index]
    raw = (
        f"From: {sender}\r\nSubject: {subject}\r\n"
        f"Date: {datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}\r\n"
        "Content-Type: text/html; charset=utf-8\r\nMIME-Version: 1.0\r\n\r\n"
        f"{body}"
    ).encode()
    return parse_message(raw, str(100 + index), "INBOX")


def selftest() -> int:
    failures: list[str] = []

    first = build_selftest_message(0)
    codes = extract_codes(first.subject, first.text)
    if not codes or codes[0]["code"] != "482913":
        failures.append(f"numeric code: got {codes!r}")
    links = extract_links(first, "example.com")
    if not links or "token=abc123def456ghi789jkl" not in links[0]["url"]:
        failures.append(f"plain link ranking: got {links!r}")
    if any("preferences" in link["url"] for link in links[:1]):
        failures.append("unsubscribe link outranked the verification link")

    second = build_selftest_message(1)
    links = extract_links(second, "example.com")
    if not links or "/account/confirm" not in links[0]["url"]:
        failures.append(f"html link extraction: got {links!r}")
    if any("pixel.gif" in link["url"] for link in links[:1]):
        failures.append("tracking pixel outranked the confirmation link")

    third = build_selftest_message(2)
    codes = extract_codes(third.subject, third.text)
    if not codes or codes[0]["code"].upper() != "K7X9P2":
        failures.append(f"alphanumeric code: got {codes!r}")

    parsed = html_to_text('<p>Hello&nbsp;there</p><script>bad()</script><p>Code <b>123456</b></p>')
    if "bad()" in parsed or "Hello there" not in parsed or "123456" not in parsed:
        failures.append(f"html_to_text: got {parsed!r}")

    alias, password = make_alias("me@gmail.com", "3hk")
    if not re.fullmatch(r"me\+3hk-[0-9a-f]{6}@gmail\.com", alias):
        failures.append(f"alias format: {alias}")
    if len(password) < 16:
        failures.append(f"password too short: {password}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print("selftest: ok (numeric code, alphanumeric code, link ranking, html, alias)")
    return 0


# --------------------------------------------------------------------------
# alias and password


def make_alias(address: str, tag: str) -> tuple[str, str]:
    local, _, domain = address.partition("@")
    local = local.split("+")[0] or "recon"
    domain = domain or "gmail.com"
    clean_tag = re.sub(r"[^a-z0-9]+", "-", (tag or "").lower()).strip("-")[:12] or "bb"
    alias = f"{local}+{clean_tag}-{secrets.token_hex(3)}@{domain}"
    return alias, make_password()


def make_password(length: int = 20) -> str:
    upper = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    lower = "abcdefghijkmnopqrstuvwxyz"
    digits = "23456789"
    symbols = "!@#$%^&*"
    alphabet = upper + lower + digits + symbols
    while True:
        value = [secrets.choice(upper), secrets.choice(lower), secrets.choice(digits), secrets.choice(symbols)]
        value += [secrets.choice(alphabet) for _ in range(max(4, length - len(value)))]
        secrets.SystemRandom().shuffle(value)
        candidate = "".join(value)
        if all(ch not in candidate for ch in "\"'\\`"):
            return candidate


# --------------------------------------------------------------------------
# CLI


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="JSON file containing {\"gmail\": {...}}")
    parser.add_argument("--address", help="override the mailbox address")
    parser.add_argument("--host", help="override the IMAP host")
    parser.add_argument("--port", type=int, help="override the IMAP port")


def add_search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--to", dest="alias", help="alias address to search for")
    parser.add_argument("--since", default="15m", help="look back this far (15m, 2h, 1d, ISO-8601)")
    parser.add_argument("--subject-re", help="only messages whose subject matches this regex")
    parser.add_argument("--from-re", help="only senders matching this regex")
    parser.add_argument("--limit", type=int, default=10, help="how many recent messages to inspect")
    parser.add_argument("--no-spam", action="store_true", help="skip the Spam mailbox")
    parser.add_argument("--json", action="store_true", help="machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mailbox.py",
        description="Read-only Gmail mailbox helper for signup verification (API or IMAP).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="verify credentials and connection")
    add_connection_args(check)
    check.add_argument("--json", action="store_true")

    alias = sub.add_parser("alias", help="generate a per-target alias and password")
    add_connection_args(alias)
    alias.add_argument("--tag", default="bb", help="target tag, e.g. 3hk")
    alias.add_argument("--json", action="store_true")

    listing = sub.add_parser("list", help="list recent messages")
    add_connection_args(listing)
    add_search_args(listing)

    wait = sub.add_parser("wait", help="wait for a new message")
    add_connection_args(wait)
    add_search_args(wait)
    wait.add_argument("--timeout", type=int, default=120, help="seconds to wait (default 120)")
    wait.add_argument("--interval", type=float, default=5.0, help="poll interval in seconds")

    otp = sub.add_parser("otp", help="wait for a message and print its best code")
    add_connection_args(otp)
    add_search_args(otp)
    otp.add_argument("--wait", type=int, default=0, help="seconds to wait before giving up")

    link = sub.add_parser("link", help="wait for a message and print the best link")
    add_connection_args(link)
    add_search_args(link)
    link.add_argument("--wait", type=int, default=0, help="seconds to wait before giving up")
    link.add_argument("--domain", help="prefer links on this registrable domain")

    read = sub.add_parser("read", help="print one message by UID")
    add_connection_args(read)
    read.add_argument("--uid", required=True)
    read.add_argument("--box", default="INBOX", help="mailbox the UID belongs to")
    read.add_argument("--domain", help="prefer links on this domain")
    read.add_argument("--json", action="store_true")

    parse = sub.add_parser(
        "parse",
        help="extract codes and links from message text (stdin or --file)",
    )
    parse.add_argument("--file", help="read the body from this file instead of stdin")
    parse.add_argument("--subject", default="", help="optional subject for context")
    parse.add_argument("--domain", help="prefer links on this domain")
    parse.add_argument("--json", action="store_true")

    sub.add_parser("selftest", help="run offline parser tests")

    return parser


def cmd_check(args) -> int:
    account = resolve_account(args)
    with open_mailbox(account) as mailbox:
        unseen = mailbox.unseen()
        if mailbox.backend == "gmail-api":
            profile = mailbox.profile()
            age_days = None
            obtained = (account.oauth or {}).get("obtained_at")
            if obtained:
                try:
                    issued = datetime.fromisoformat(str(obtained).replace("Z", "+00:00"))
                    if issued.tzinfo is None:
                        issued = issued.replace(tzinfo=timezone.utc)
                    age_days = round(
                        (datetime.now(timezone.utc) - issued).total_seconds() / 86400, 1
                    )
                except (TypeError, ValueError):
                    age_days = None
            note = None
            if age_days is not None and age_days >= 6:
                note = (
                    "refresh token is %.1f days old. Testing-mode tokens expire 7 days "
                    "after consent: publish the app to In production or re-run "
                    "oauth_setup.py." % age_days
                )
            result = {
                "ok": True,
                "address": profile.get("emailAddress") or account.address,
                "backend": "gmail-api",
                "scope": (account.oauth or {}).get("scope") or GMAIL_READONLY_SCOPE,
                "messages_total": profile.get("messagesTotal"),
                "threads_total": profile.get("threadsTotal"),
                "unseen_inbox": unseen,
                "refresh_token_age_days": age_days,
                "refresh_token_note": note,
            }
        else:
            all_mail = (
                mailbox.special_mailbox("All", "[Gmail]/All Mail")
                if mailbox.is_gmail
                else None
            )
            result = {
                "ok": True,
                "address": account.address,
                "backend": "imap",
                "imap": f"{account.host}:{account.port}",
                "gmail_extensions": mailbox.is_gmail,
                "all_mail": all_mail,
                "unseen_inbox": unseen,
            }
    if args.json:
        print_json(result)
    elif result["backend"] == "gmail-api":
        print(f"OK  {result['address']} via Gmail API (read-only)")
        print(f"    messages      : {result['messages_total']}")
        print(f"    unseen inbox  : {result['unseen_inbox']}")
        print(f"    token age     : {result['refresh_token_age_days']} days")
        if result["refresh_token_note"]:
            print(f"    warning       : {result['refresh_token_note']}")
    else:
        print(f"OK  {result['address']} via {result['imap']}")
        print(f"    gmail extensions: {result['gmail_extensions']}")
        if result["all_mail"]:
            print(f"    all mail box   : {result['all_mail']}")
        print(f"    unseen inbox   : {result['unseen_inbox']}")
    return 0


def cmd_alias(args) -> int:
    account = resolve_account(args, require_password=False)
    alias, password = make_alias(account.address, args.tag)
    result = {
        "alias": alias,
        "password": password,
        "signup_address": alias,
        "inbox": account.address,
        "tag": args.tag,
        "note": "Gmail delivers +alias mail to the base inbox; search with --to this alias.",
    }
    if args.json:
        print_json(result)
    else:
        print(f"alias    : {alias}")
        print(f"password : {password}")
        print(f"inbox    : {account.address}")
    return 0


def _search_from_args(args, mailbox: ImapMailbox) -> Message | None:
    since = parse_since(args.since)
    return wait_for_message(
        mailbox,
        args.alias,
        since=since,
        timeout=getattr(args, "wait", 0),
        interval=getattr(args, "interval", 5.0),
        limit=max(1, args.limit),
        subject_re=args.subject_re,
        from_re=args.from_re,
        include_spam=not args.no_spam,
    )


def cmd_list(args) -> int:
    account = resolve_account(args)
    since = parse_since(args.since)
    days = max(1, math.ceil(since.total_seconds() / 86400) + 1)
    cutoff = datetime.now(timezone.utc) - since
    with open_mailbox(account) as mailbox:
        messages = mailbox.search(
            args.alias,
            days=days,
            limit=max(1, args.limit),
            include_spam=not args.no_spam,
        )
        messages = [
            message
            for message in messages
            if keep(message, cutoff, args.subject_re, args.from_re)
        ]
    if args.json:
        print_json([message_dict(message) for message in messages])
        return 0 if messages else 3
    if not messages:
        print("no matching messages", file=sys.stderr)
        return 3
    for message in messages:
        stamp = message.date.isoformat() if message.date else "unknown-date"
        print(f"[{message.uid}] {stamp}  {message.subject}")
        print(f"      from {message.sender}  ({message.mailbox})")
    return 0


def cmd_wait(args) -> int:
    account = resolve_account(args)
    with open_mailbox(account) as mailbox:
        message = wait_for_message(
            mailbox,
            args.alias,
            since=parse_since(args.since),
            timeout=args.timeout,
            interval=args.interval,
            limit=max(1, args.limit),
            subject_re=args.subject_re,
            from_re=args.from_re,
            include_spam=not args.no_spam,
        )
    if message is None:
        if args.json:
            print_json({"ok": False, "reason": "timeout", "alias": args.alias})
        else:
            print("timeout: no matching message", file=sys.stderr)
        return 3
    if args.json:
        print_json(message_dict(message))
    else:
        print_message(message)
    return 0


def cmd_otp(args) -> int:
    account = resolve_account(args)
    with open_mailbox(account) as mailbox:
        message = _search_from_args(args, mailbox)
        if message is None:
            if args.json:
                print_json({"ok": False, "reason": "timeout", "alias": args.alias})
            else:
                print("timeout: no matching message", file=sys.stderr)
            return 3
        payload = message_dict(message)
        if not payload["codes"]:
            if args.json:
                payload.update(ok=False, reason="no code found")
                print_json(payload)
            else:
                print("no code found in the message", file=sys.stderr)
                print_message(message)
            return 3
    if args.json:
        print_json(payload)
    else:
        print(payload["codes"][0]["code"])
        print(f"# from {payload['from']} / {payload['subject']}", file=sys.stderr)
    return 0


def cmd_link(args) -> int:
    account = resolve_account(args)
    with open_mailbox(account) as mailbox:
        message = _search_from_args(args, mailbox)
        if message is None:
            if args.json:
                print_json({"ok": False, "reason": "timeout", "alias": args.alias})
            else:
                print("timeout: no matching message", file=sys.stderr)
            return 3
        payload = message_dict(message, domain=args.domain)
        if not payload["links"]:
            if args.json:
                payload.update(ok=False, reason="no link found")
                print_json(payload)
            else:
                print("no link found in the message", file=sys.stderr)
                print_message(message)
            return 3
    if args.json:
        print_json(payload)
    else:
        print(payload["links"][0]["url"])
        print(f"# from {payload['from']} / {payload['subject']}", file=sys.stderr)
    return 0


def cmd_parse(args) -> int:
    if args.file:
        try:
            text = Path(args.file).expanduser().read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise MailboxError(f"cannot read {args.file}: {exc}") from exc
    else:
        text = sys.stdin.read()
    if not text.strip():
        raise MailboxError("no message text on stdin; pipe a body or use --file")

    plain = text
    if re.search(r"(?is)<(html|body|div|p|a)\b", text):
        plain = html_to_text(text)
    message = Message(
        uid="",
        mailbox="stdin",
        subject=args.subject,
        sender="",
        date=None,
        text=plain,
        html=text if plain is not text else "",
    )
    codes = extract_codes(args.subject, plain)
    links = extract_links(message, args.domain)
    payload = {
        "ok": bool(codes or links),
        "codes": codes,
        "links": links,
        "excerpt": excerpt(plain),
    }
    if args.json:
        print_json(payload)
    else:
        if codes:
            print(f"code : {codes[0]['code']}")
            for candidate in codes[1:]:
                print(f"alt  : {candidate['code']}")
        if links:
            print("links:")
            for link in links[:5]:
                print(f"  [{link['score']:>2}] {link['url']}")
        if not codes and not links:
            print("no code or link found", file=sys.stderr)
            print(payload["excerpt"][:300])
    return 0 if payload["ok"] else 3


def cmd_read(args) -> int:
    account = resolve_account(args)
    with open_mailbox(account) as mailbox:
        if not mailbox.select(args.box):
            raise MailboxError(f"cannot open mailbox {args.box!r}")
        message = mailbox.fetch(str(args.uid), args.box)
    if message is None:
        print(f"uid {args.uid} not found in {args.box}", file=sys.stderr)
        return 3
    if args.json:
        print_json(message_dict(message, domain=args.domain))
    else:
        print_message(message, domain=args.domain)
        print()
        print(message.text[:4000])
    return 0


def cmd_parse(args) -> int:
    if args.file:
        try:
            raw = Path(args.file).expanduser().read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise MailboxError(f"cannot read {args.file}: {exc}") from exc
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise MailboxError("no message text on stdin or --file")

    html = ""
    body = raw
    lowered = raw.lower()
    if any(tag in lowered for tag in ("<html", "<body", "<div", "<table", "<p>")):
        html = raw
        body = html_to_text(raw)

    message = Message(
        uid="",
        mailbox="parse",
        subject=args.subject,
        sender="",
        date=None,
        text=body,
        html=html,
    )
    payload = {
        "ok": True,
        "subject": args.subject,
        "codes": extract_codes(args.subject, body),
        "links": extract_links(message, args.domain),
        "excerpt": excerpt(body),
    }
    if args.json:
        print_json(payload)
    else:
        if payload["codes"]:
            print(f"code: {payload['codes'][0]['code']} (score {payload['codes'][0]['score']})")
            for candidate in payload["codes"][1:]:
                print(f"  alt: {candidate['code']} (score {candidate['score']})")
        for link in payload["links"][:5]:
            print(f"link [{link['score']:>2}] {link['url']}")
        if not payload["codes"] and not payload["links"]:
            print("no code or link found", file=sys.stderr)
    return 0 if payload["codes"] or payload["links"] else 3


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "check": cmd_check,
        "alias": cmd_alias,
        "list": cmd_list,
        "wait": cmd_wait,
        "otp": cmd_otp,
        "link": cmd_link,
        "read": cmd_read,
        "parse": cmd_parse,
    }
    if args.command == "selftest":
        return selftest()
    try:
        return commands[args.command](args)
    except MailboxError as exc:
        message = str(exc)
        if getattr(args, "json", False):
            print_json({"ok": False, "reason": message})
        else:
            print(f"mailbox: {message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
