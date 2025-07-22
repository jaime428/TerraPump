import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth as _auth

svc_acct = dict(st.secrets["firebase_admin"])

svc_acct["private_key"] = svc_acct["private_key"].replace("\\n", "\n")

if not firebase_admin._apps:
    cred = credentials.Certificate(svc_acct)
    firebase_admin.initialize_app(cred)

db   = firestore.client()
auth = _auth
