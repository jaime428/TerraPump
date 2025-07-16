import firebase_admin
from firebase_admin import credentials, firestore
import pyrebase
import os

# --- Firebase Admin SDK (for Firestore) ---
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cred_path = os.path.join(base_dir, "data", "terrapump-e86f6-firebase-adminsdk-fbsvc-adb5f6bdd4.json")
cred = credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()  # ✅ Firestore database client

# --- Firebase Client SDK (for Auth) ---
firebase_config = {
    "apiKey": "AIzaSyDpANDAFYzIOP5BAiSsyyY_zDUjQ5tEZcE",
    "authDomain": "terrapump-e86f6.firebaseapp.com",
    "projectId": "terrapump-e86f6",
    "storageBucket": "terrapump-e86f6.appspot.com",
    "messagingSenderId": "963467680698",
    "appId": "1:963467680698:web:8c775d29ef53aa8b969b83",
    "databaseURL": "https://terrapump-e86f6-default-rtdb.firebaseio.com/",
    "measurementId": "G-3NKQQSBVDL"
}

firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()