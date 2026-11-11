"""The streep system feeds the Francken pet: every snack or drink streeped at consumption-counter.professorfrancken.nl
(the PC next to the fridge) gives it food, and it pops up in the corner of whatever slide is on to say thank you
("Thank you for the Twix!", "+1": PetProvider.overlay()). Who streeped is never shown, only what.

The streep system's API (the one its web app uses, https://professorfrancken.nl/api/plus-one) needs its password,
in ~/.config/slideshow/streep.json on the TV PC: {"password": "..."} (docs/02-accounts-and-secrets.md). Without
that file nothing happens. GET /orders lists the recent orders; the first time after a start only remembers them,
so a restart doesn't feed the pet with old orders.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

import requests


log = logging.getLogger(__name__)

API = "https://professorfrancken.nl/api/plus-one"
PRODUCTS_EVERY = timedelta(hours=6)   # the product list (names, categories) changes rarely
MAX_NAMED = 3                          # "Twix, Cola and Hertog Jan", more: "and 2 more"


def kind_of(category: str) -> str:
	"""What drops into its mouth: "beer", "soda" or "food", from the product's category in the streep system."""
	category = (category or "").lower()
	if "bier" in category or "beer" in category:
		return "beer"
	if "fris" in category or "drink" in category or "soda" in category:
		return "soda"
	return "food"


def order_key(order: dict) -> str:
	"""An order's identity: its id if it has one, else who, what and when."""
	if order.get("id") is not None:
		return f"id:{order['id']}"
	return f"{order.get('member_id')}|{order.get('product_id')}|{order.get('ordered_at')}"


def listing(names: list[str]) -> str:
	"""["Twix", "Cola", "Mars", "Tuc"] -> "Twix, Cola, Mars and 1 more"."""
	shown = names[:MAX_NAMED]
	rest = len(names) - len(shown)
	if rest:
		return f"{', '.join(shown)} and {rest} more"
	return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


class StreepFeed:
	"""Polls the streep system for new orders (poll(), from the pet's refresh()) and keeps them until the pet
	says thank you for them (take())."""

	def __init__(self, credentials: Path, session: requests.Session | None = None) -> None:
		self.credentials = credentials
		self.session = session or requests.Session()
		self.token: str | None = None
		self.products: dict[int, dict] = {}   # id -> {"name", "kind"}
		self.products_read: datetime | None = None
		self.seen: set[str] | None = None     # the orders already counted; None until the first poll
		self.pending: list[dict] = []         # new orders, not shown yet: {"name", "kind"}
		self.lock = threading.Lock()

	@property
	def configured(self) -> bool:
		return self.credentials.is_file()

	def password(self) -> str:
		return json.loads(self.credentials.read_text(encoding="utf-8"))["password"]

	def get(self, path: str) -> dict:
		"""GET from the API, logging in first (and again once the token expired)."""
		for attempt in range(2):
			if self.token is None:
				response = self.session.post(f"{API}/authenticate", json={"password": self.password()}, timeout=20)
				response.raise_for_status()
				self.token = response.json()["token"]
			response = self.session.get(f"{API}{path}", headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
			if response.status_code in (401, 403) and attempt == 0:
				self.token = None   # expired: log in again
				continue
			response.raise_for_status()
			return response.json()
		raise RuntimeError("unreachable")

	def read_products(self, now: datetime) -> None:
		if self.products and self.products_read and now - self.products_read < PRODUCTS_EVERY:
			return
		products = {}
		for product in self.get("/products").get("products", []):
			try:
				products[int(product["id"])] = {"name": product.get("naam") or product.get("name") or "something",
					"kind": kind_of(product.get("categorie") or product.get("category") or "")}
			except (KeyError, TypeError, ValueError):
				continue
		self.products, self.products_read = products, now

	def poll(self, now: datetime) -> list[dict]:
		"""Fetch the orders; returns the new ones as {"name", "kind"} (none the first time: those are only remembered)."""
		if not self.configured:
			return []
		self.read_products(now)
		orders = self.get("/orders").get("orders") or []
		keys = {order_key(order): order for order in orders if isinstance(order, dict)}
		with self.lock:
			if self.seen is None:
				self.seen = set(keys)
				return []
			new = [order for key, order in keys.items() if key not in self.seen]
			self.seen |= set(keys)
			if len(self.seen) > 5000:
				self.seen = set(keys)   # keep it small; what's still listed is all that matters
			bought = []
			for order in new:
				try:
					bought.append(self.products.get(int(order.get("product_id")), {"name": "something", "kind": "food"}))
				except (TypeError, ValueError):
					bought.append({"name": "something", "kind": "food"})
			self.pending += bought
		if bought:
			log.info("Streep system: %d new order(s) for the pet", len(bought))
		return bought

	def take(self) -> list[dict]:
		with self.lock:
			pending, self.pending = self.pending, []
		return pending
