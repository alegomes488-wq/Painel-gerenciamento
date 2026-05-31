import firebase_admin
from firebase_admin import credentials, db
import os

project_root = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(project_root, "firebase-secrets", "firebase-adminsdk.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'
    })

def check_wid(wid):
    all_withdrawals = db.reference('withdrawals').get() or {}
    for uid, ws in all_withdrawals.items():
        if isinstance(ws, dict) and wid in ws:
            print(f"Encontrado: UID={uid}, Data={ws[wid]}")
            return uid, ws[wid]
    print("Saque não encontrado.")
    return None, None

if __name__ == "__main__":
    check_wid("02d19685")
