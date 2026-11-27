"""Google Analytics 4: deleting the events of a deleted account (the app sends them, flueai-app
docs/analytics-ga4.md).

The app sends GA4 the account id as User-ID. When the account goes, the Admin API's
`properties.submitUserDeletion` asks GA4 to delete everything under that User-ID. A service account
signs in by the OAuth 2.0 JWT bearer flow (RS256 with its private key, PyJWT); no Google SDK.
"""
import json
import time

import jwt

from app.core.config import get_settings
from app.core.http import http_client

SCOPE = "https://www.googleapis.com/auth/analytics.edit"
TOKEN_URI = "https://oauth2.googleapis.com/token"
ADMIN_API = "https://analyticsadmin.googleapis.com/v1alpha"


async def _access_token(account: dict) -> str:
    now = int(time.time())
    token_uri = account.get("token_uri") or TOKEN_URI
    assertion = jwt.encode(
        {"iss": account["client_email"], "scope": SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600},
        account["private_key"],
        algorithm="RS256",
    )
    async with http_client(timeout=15.0) as client:
        response = await client.post(
            token_uri,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
    response.raise_for_status()
    return response.json()["access_token"]


async def delete_user(user_id: str) -> bool:
    """Asks GA4 to delete the events of this User-ID. False when GA4 is not configured here."""
    settings = get_settings()
    if not (settings.ga4_property_id and settings.ga4_service_account_json):
        return False
    account = json.loads(settings.ga4_service_account_json)
    token = await _access_token(account)
    async with http_client(timeout=15.0) as client:
        response = await client.post(
            f"{ADMIN_API}/properties/{settings.ga4_property_id}:submitUserDeletion",
            json={"userId": user_id},
            headers={"Authorization": f"Bearer {token}"},
        )
    response.raise_for_status()
    return True
