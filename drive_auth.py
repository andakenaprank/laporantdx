# drive_auth.py — generate GOOGLE_TOKEN (base64 of pickle-serialized Credentials)
import base64, pickle, json, os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Scopes hanya untuk Drive user-delegated
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Simpan rahasia OAuth Desktop (client_id/secret) sebagai JSON file lokal
# atau lewat env GOOGLE_OAUTH_CLIENT_JSON
CLIENT_JSON_PATH = os.getenv("GOOGLE_OAUTH_CLIENT_JSON", "credentials.json")

def main():
    if not Path(CLIENT_JSON_PATH).exists():
        raise SystemExit(f"❌ File {CLIENT_JSON_PATH} tidak ditemukan. Unduh JSON OAuth Desktop dari Google Cloud Console.")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_JSON_PATH, SCOPES)
    # gunakan local server flow (aman, modern; OOB sudah deprecated)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline", include_granted_scopes="true")

    # pastikan ada refresh token
    if not creds.refresh_token:
        raise SystemExit("❌ Tidak ada refresh_token. Pastikan 'access_type=offline' dan akun mengizinkan.")

    token_pickled = pickle.dumps(creds)
    token_b64 = base64.b64encode(token_pickled).decode("utf-8")

    print("\n✅ GOOGLE_TOKEN (paste ke .env):\n")
    print(token_b64)
    print("\nSimpan ke .env sebagai:\nGOOGLE_TOKEN=" + token_b64)

if __name__ == "__main__":
    main()
