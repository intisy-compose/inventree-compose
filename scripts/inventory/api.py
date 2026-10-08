"""A small InvenTree REST client on the standard library, so the catalog tool needs no extra packages."""

import base64
import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request


class ApiError(Exception):
    pass


class Client:
    def __init__(self, base_url, user, password):
        self.base_url = base_url.rstrip("/")
        self.token = self._fetch_token(user, password)

    def _fetch_token(self, user, password):
        credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
        request = urllib.request.Request(f"{self.base_url}/api/user/token/", headers={"Authorization": f"Basic {credentials}"})
        return self._send(request)["token"]

    def get(self, path, **params):
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        return self._request("GET", f"{path}{query}")

    def post(self, path, body):
        return self._request("POST", path, body)

    def patch(self, path, body):
        return self._request("PATCH", path, body)

    def delete(self, path):
        return self._request("DELETE", path)

    def upload(self, path, field, file_name, data):
        """PATCHes one file as multipart/form-data, the only way the API takes an image."""
        boundary = secrets.token_hex(16)
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{os.path.basename(file_name)}\"\r\n"
                f"Content-Type: {content_type}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        request = self._prepare("PATCH", path, body, f"multipart/form-data; boundary={boundary}")
        return self._send(request)

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        return self._send(self._prepare(method, path, data, "application/json"))

    def _prepare(self, method, path, data, content_type):
        headers = {"Authorization": f"Token {self.token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = content_type
        return urllib.request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)

    def _send(self, request):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:1000]
            raise ApiError(f"{request.get_method()} {request.full_url}: HTTP {error.code} {detail}")
        except urllib.error.URLError as error:
            raise ApiError(f"{request.full_url}: {error.reason}")
        return json.loads(payload) if payload else None
