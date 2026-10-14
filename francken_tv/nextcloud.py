"""A tiny Nextcloud (WebDAV) client: list folders and download files."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

import requests

DAV = {"d": "DAV:"}


@dataclass
class Entry:
	path: str        # relative to the user's root, e.g. "images/albums/2026/2026-10-12-Dies-Natalis/"
	is_folder: bool

	@property
	def name(self) -> str:
		return self.path.rstrip("/").rsplit("/", 1)[-1]


def load_credentials(path: Path) -> tuple[str, str]:
	"""Accepts {"username": ..., "password": ...} or [{"username": ...}, {"password": ...}]."""
	data = json.loads(path.read_text(encoding="utf-8"))
	if isinstance(data, list):
		merged = {}
		for item in data:
			merged.update(item)
		data = merged
	return data["username"], data["password"]


class Nextcloud:
	def __init__(self, server: str, username: str, password: str) -> None:
		self.root = f"{server.rstrip('/')}/remote.php/dav/files/{quote(username)}/"
		self.session = requests.Session()
		self.session.auth = (username, password)

	def list_folder(self, path: str) -> list[Entry]:
		response = self.session.request("PROPFIND", self.root + quote(path), headers={"Depth": "1"}, timeout=30)
		response.raise_for_status()
		entries = []
		root_path = unquote(requests.utils.urlparse(self.root).path)
		for item in ElementTree.fromstring(response.content).findall("d:response", DAV):
			full = unquote(item.find("d:href", DAV).text)
			relative = full[len(root_path):] if full.startswith(root_path) else full
			if relative.rstrip("/") == path.rstrip("/"):
				continue   # the folder itself
			is_folder = item.find(".//d:resourcetype/d:collection", DAV) is not None
			entries.append(Entry(relative, is_folder))
		return entries

	def download(self, path: str, destination: Path) -> None:
		response = self.session.get(self.root + quote(path), timeout=60)
		response.raise_for_status()
		temporary = destination.with_suffix(destination.suffix + ".part")
		temporary.write_bytes(response.content)
		temporary.replace(destination)
