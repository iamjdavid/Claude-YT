"""One-time helper: get a YouTube refresh token for automatic uploads.

1. Google Cloud Console -> create project -> enable "YouTube Data API v3".
2. OAuth consent screen (External, add yourself as test user) -> Credentials ->
   Create OAuth client ID -> "Desktop app" -> download JSON as client_secret.json.
3. Run on your own computer:  python scripts/get_youtube_token.py client_secret.json
4. Save the printed values as GitHub secrets YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]

path = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(path))
client = info.get("installed") or info.get("web")
print("\nAdd these as GitHub repository secrets:\n")
print("YT_CLIENT_ID     =", client["client_id"])
print("YT_CLIENT_SECRET =", client["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
