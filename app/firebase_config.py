import os
import firebase_admin
from firebase_admin import credentials

# Point to the secure key location
cred_path = os.path.join("secrets", "credentials.json")

# Initialize Firebase Admin SDK
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
