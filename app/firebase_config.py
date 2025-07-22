# app/firebase_config.py
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pyrebase

# ————————————— Admin SDK (server) —————————————
# copy & fix your private key, initialize once
svc_acct = dict(st.secrets["firebase_admin"])
svc_acct["private_key"] = svc_acct["private_key"].replace("\\n","\n")
if not firebase_admin._apps:
    cred = credentials.Certificate(svc_acct)
    firebase_admin.initialize_app(cred)

# Firestore client for reading/writing your DB
db = firestore.client()


# ————————————— Client SDK (user auth) —————————————
# grab your web-config from the [firebase] block in secrets.toml
pb_cfg = st.secrets["firebase"]
# initialize the Pyrebase app
_pyfb = pyrebase.initialize_app(pb_cfg)
# this is what you should use in your login page
client_auth = _pyfb.auth()
