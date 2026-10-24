"""Dünne Schicht über die Supabase-REST-API (PostgREST).

Bewusst ohne supabase-py, damit die Abhängigkeiten klein bleiben. Der Scraper
läuft serverseitig und nutzt den Service-Role-Key, der RLS umgeht. Der Key
gehört ausschließlich in die .env bzw. in die Secrets des Zielsystems.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

PAGE_SIZE = 1000


class SupabaseError(RuntimeError):
    pass


class SupabaseClient:
    def __init__(self, url: str, service_role_key: str, timeout: float = 30.0):
        if not url or not service_role_key:
            raise SupabaseError(
                "SUPABASE_URL und SUPABASE_SERVICE_ROLE_KEY müssen gesetzt sein (siehe .env.example)"
            )
        self.base = url.rstrip("/") + "/rest/v1"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        resp = self.session.request(
            method, f"{self.base}/{path}", timeout=self.timeout, **kwargs
        )
        if resp.status_code >= 400:
            raise SupabaseError(f"{method} {path} fehlgeschlagen: {resp.status_code} {resp.text[:500]}")
        return resp

    def fetch_companies(self) -> list[dict]:
        """Lädt alle Firmen seitenweise (id, name, city, domain)."""
        rows: list[dict] = []
        offset = 0
        while True:
            resp = self._request(
                "GET",
                "companies",
                params={"select": "id,name,city,domain", "order": "created_at.asc"},
                headers={"Range-Unit": "items", "Range": f"{offset}-{offset + PAGE_SIZE - 1}"},
            )
            page = resp.json()
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows
            offset += PAGE_SIZE

    def insert_company(self, company: dict) -> dict:
        """Legt eine Firma an und gibt die gespeicherte Zeile (mit id) zurück."""
        resp = self._request(
            "POST",
            "companies",
            json=company,
            headers={"Prefer": "return=representation"},
        )
        data = resp.json()
        return data[0] if isinstance(data, list) else data

    def insert_signals(self, signals: list[dict]) -> int:
        """Fügt Signale ein und ignoriert Duplikate über UNIQUE(company_id, signal_type_id, url).

        Gibt die Anzahl tatsächlich neu angelegter Signale zurück.
        """
        if not signals:
            return 0
        resp = self._request(
            "POST",
            "signals",
            params={"on_conflict": "company_id,signal_type_id,url"},
            json=signals,
            headers={"Prefer": "resolution=ignore-duplicates,missing=default,return=representation"},
        )
        return len(resp.json())
