import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth as _auth

firebase_secrets = st.secrets["firebase"]
firebase_secrets["private_key"] = firebase_secrets["private_key"].replace("\\n", "\n")

if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_secrets)
    firebase_admin.initialize_app(cred)

db   = firestore.client()
auth = _auth
