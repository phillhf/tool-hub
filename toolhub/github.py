"""Zugriff auf die GitHub-API: Repos, Releases und Downloads, mit oder ohne Token."""
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import OWNER, __version__

API = "https://api.github.com"


class GitHubError(Exception):
    pass


class _KeepAuthOnSameHost(urllib.request.HTTPRedirectHandler):
    """Downloads leiten zu einem Speicher-Server weiter; der darf den Token nicht sehen."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            new.remove_header("Authorization")
        return new


_opener = urllib.request.build_opener(_KeepAuthOnSameHost)


def next_link(header):
    """URL der nächsten Seite aus dem Link-Header, sonst None."""
    for part in (header or "").split(","):
        match = re.search(r'<([^>]+)>\s*;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


class Api:
    def __init__(self, token=None, cache=None, owner=OWNER):
        self.token = token or None
        self.owner = owner
        # url -> {"etag": ..., "data": ...}; Antworten 304 zählen nicht gegen das Abfragelimit
        self.cache = cache if cache is not None else {}
        self.offline = False
        self._lock = threading.Lock()

    def _request(self, url, accept="application/vnd.github+json", etag=None):
        headers = {"User-Agent": f"Tool-Hub/{__version__}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if etag:
            headers["If-None-Match"] = etag
        return urllib.request.Request(url, headers=headers)

    def get(self, path):
        """GET mit Zwischenspeicher. Liefert (Daten, Antwort-Header); 404 ergibt (None, {})."""
        url = path if path.startswith("http") else API + path
        key = f"{'auth' if self.token else 'anon'} {url}"
        with self._lock:
            cached = self.cache.get(key)
        try:
            with _opener.open(self._request(url, etag=cached and cached.get("etag")), timeout=20) as response:
                data = json.load(response)
                link = response.headers.get("Link", "")
                with self._lock:
                    self.cache[key] = {"etag": response.headers.get("ETag"), "data": data, "link": link}
                return data, {"link": link}
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and cached:
                return cached["data"], {"link": cached.get("link", "")}
            if exc.code == 404:
                return None, {}
            if exc.code == 401:
                raise GitHubError("Der GitHub-Token ist ungültig oder abgelaufen.") from exc
            if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
                if cached:
                    return cached["data"], {"link": cached.get("link", "")}
                raise GitHubError("GitHub-Abfragelimit erreicht. In einer Stunde geht es weiter, "
                                  "mit einem Token sofort.") from exc
            raise GitHubError(f"GitHub antwortet mit Fehler {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if cached:
                self.offline = True
                return cached["data"], {"link": cached.get("link", "")}
            raise GitHubError("Keine Verbindung zu GitHub.") from exc

    def get_all(self, path):
        items, url = [], path
        while url:
            data, headers = self.get(url)
            items.extend(data or [])
            url = next_link(headers.get("link"))
        return items

    def user(self):
        data, _ = self.get("/user")
        return data

    def repos(self):
        """Alle Repos des Besitzers; mit Token auch die privaten, auf die der Token Zugriff hat."""
        if self.token:
            repos = self.get_all("/user/repos?per_page=100&affiliation=owner,collaborator,organization_member")
        else:
            repos = self.get_all(f"/users/{self.owner}/repos?per_page=100&type=owner")
        return [r for r in repos if r.get("owner", {}).get("login", "").lower() == self.owner.lower()]

    def latest_release(self, repo):
        data, _ = self.get(f"/repos/{self.owner}/{repo}/releases/latest")
        return data

    def download(self, asset, folder, progress=lambda percent: None):
        """Lädt ein Release-Asset (auch aus privaten Repos) und prüft die SHA-256-Prüfsumme."""
        target = os.path.join(folder, asset["name"])
        digest = hashlib.sha256()
        request = self._request(asset["url"], accept="application/octet-stream")
        try:
            with _opener.open(request, timeout=60) as response, open(target, "wb") as f:
                total = int(response.headers.get("Content-Length") or asset.get("size") or 0)
                loaded = 0
                while chunk := response.read(256 * 1024):
                    f.write(chunk)
                    digest.update(chunk)
                    loaded += len(chunk)
                    if total:
                        progress(min(100, loaded * 100 // total))
        except urllib.error.HTTPError as exc:
            raise GitHubError(f"Download fehlgeschlagen (Fehler {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubError(f"Download fehlgeschlagen: {exc}") from exc
        expected = asset.get("digest") or ""
        if expected.startswith("sha256:") and expected != f"sha256:{digest.hexdigest()}":
            os.remove(target)
            raise GitHubError("Die Prüfsumme des Downloads stimmt nicht, die Datei wurde verworfen.")
        return target
