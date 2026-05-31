import firebase_admin
from firebase_admin import credentials, db
import os
import sys

# Garante que o terminal aceite caracteres especiais se possivel
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Caminho para a nova chave
project_root = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(project_root, "firebase-secrets", "firebase-adminsdk.json")

print(f"Testing key at: {cred_path}")

if not os.path.exists(cred_path):
    print("ERROR: File not found!")
    exit()

try:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'
    })
    
    # Teste de leitura
    print("Connecting to Firebase...")
    config = db.reference('config').get()
    
    if config is not None:
        print("SUCCESS: CONNECTION ESTABLISHED!")
        # Evitando emojis para nao quebrar o terminal Windows
        print(f"System Status: {config.get('status', 'N/A')}")
        print(f"Current CPM: {config.get('cpm', 'N/A')}")
    else:
        print("WARNING: Connected, but 'config' node is empty.")
        
except Exception as e:
    print(f"FAILURE: {str(e)}")
