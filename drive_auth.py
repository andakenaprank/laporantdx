from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pickle

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def main():
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)

    # simpan token biar gak perlu login ulang
    with open('token.pickle', 'wb') as token:
        pickle.dump(creds, token)
    print("✅ Token berhasil dibuat!")

if __name__ == '__main__':
    main()
