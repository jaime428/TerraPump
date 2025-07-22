# app/firebase_config.py
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth as _auth

# 1) pull from the correct block
svc_acct = dict(st.secrets["firebase_admin"])

# 2) turn those "\n" sequences into real newlines
svc_acct["private_key"] = svc_acct["private_key"].replace("\\n", "\n")

# 3) initialize once
if not firebase_admin._apps:
    cred = credentials.Certificate(svc_acct)
    firebase_admin.initialize_app(cred)

# 4) export the handles you need elsewhere
db   = firestore.client()
auth = _auth
