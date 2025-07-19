import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pyrebase

# --- Admin SDK (used for Firestore) ---
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --- Pyrebase client-side config (used for login/auth) ---
firebase_config = {
    "apiKey": st.secrets["firebase_apiKey"],
    "authDomain": st.secrets["firebase_authDomain"],
    "projectId": st.secrets["firebase"]["project_id"],
    "storageBucket": st.secrets["firebase_storageBucket"],
    "messagingSenderId": st.secrets["firebase_messagingSenderId"],
    "appId": st.secrets["firebase_appId"],
    "measurementId": st.secrets["firebase_measurementId"]
}

firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()
