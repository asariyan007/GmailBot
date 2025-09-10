import urllib.parse
from google_auth_oauthlib.flow import Flow
import os

# Use credentials.json from Google Cloud Console
CLIENT_SECRETS_FILE = "credentials.json"
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def generate_oauth_link(tg_id, redirect_uri):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    state = str(tg_id)
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        state=state,
        prompt='consent'
    )
    return auth_url

async def exchange_code_for_tokens(code):
    from google.oauth2.credentials import Credentials
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=os.getenv("OAUTH_REDIRECT_URI")
    )
    flow.fetch_token(code=code)
    credentials = flow.credentials
    email = credentials.id_token.get("email")
    return credentials.token, credentials.refresh_token, email
