"""Lectura y escritura del bucket o de un directorio local con las mismas rutas."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class DataRoot:
    def read_text(self, key: str) -> str | None:
        raise NotImplementedError

    def write_text(self, key: str, text: str) -> None:
        raise NotImplementedError


class LocalRoot(DataRoot):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def read_text(self, key: str) -> str | None:
        path = self.root / key
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write_text(self, key: str, text: str) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class GcsRoot(DataRoot):
    def __init__(self, bucket: str, token_provider=None) -> None:
        self.bucket = bucket
        self.token_provider = token_provider or metadata_token

    def read_text(self, key: str) -> str | None:
        url = f"https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/{_quote(key)}?alt=media"
        status, body = _request("GET", url, self.token_provider())
        if status == 404:
            return None
        if status != 200:
            return None
        return body.decode("utf-8")

    def write_text(self, key: str, text: str) -> None:
        url = f"https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o?uploadType=media&name={_quote(key)}"
        status, _body = _request("POST", url, self.token_provider(), text.encode("utf-8"), "application/json")
        if status not in (200, 201):
            raise RuntimeError(f"no se pudo escribir {key}")


def data_root_from_env() -> DataRoot:
    bucket = os.environ.get("MESA_BUCKET", "").strip()
    if bucket:
        return GcsRoot(bucket)
    path = os.environ.get("MESA_DATA_DIR", "/tmp/mesa-trading")
    return LocalRoot(Path(path))


def metadata_token() -> str:
    url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=2) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["access_token"])


class GcpSecretKey:
    """Lee el secreto en el momento de la llamada. Si no hay versión, devuelve None."""

    def __init__(self, project: str, secret_id: str, token_provider=None) -> None:
        self.project = project
        self.secret_id = secret_id
        self.token_provider = token_provider or metadata_token

    def load(self) -> str | None:
        try:
            token = self.token_provider()
            url = (
                "https://secretmanager.googleapis.com/v1/projects/"
                f"{self.project}/secrets/{self.secret_id}/versions/latest:access"
            )
            status, body = _request("GET", url, token)
            if status != 200:
                return None
            payload = json.loads(body.decode("utf-8"))
            import base64

            data = payload.get("payload", {}).get("data")
            if not data:
                return None
            return base64.b64decode(data).decode("utf-8").strip() or None
        except Exception:
            return None


def _quote(key: str) -> str:
    return key.replace("/", "%2F")


def _request(method: str, url: str, token: str, body: bytes | None = None, content_type: str = "application/json"):  # noqa: E302
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()

