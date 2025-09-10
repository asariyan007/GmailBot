import os
import json
from google_auth_oauthlib.flow import Flow

# Gmail scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_flow(redirect_uri, state=None):
    """
    Create an OAuth2 flow from credentials stored in ENV variable
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if not creds_json:
        raise RuntimeError("Missing GOOGLE_CREDENTIALS in environment variables")
    client_config = json.loads(creds_json)

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    if state:
        flow.state = state
    return flow

def generate_oauth_link(tg_id, redirect_uri):
    """
    Generate Google OAuth link for a Telegram user
    """
    flow = get_flow(redirect_uri, state=str(tg_id))
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    return auth_url

async def exchange_code_for_tokens(code):
    """
    Exchange code for access + refresh tokens and extract Gmail address
    """
    from google.oauth2.credentials import Credentials
    redirect_uri = os.getenv("OAUTH_REDIRECT_URI")
    flow = get_flow(redirect_uri)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    email = credentials.id_token.get("email")
    return credentials.token, credentials.refresh_token, email
