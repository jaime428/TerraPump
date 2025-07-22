# app/firebase_config.py

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pyrebase

svc_acct = dict(st.secrets["firebase_admin"])
svc_acct["private_key"] = svc_acct["private_key"].replace("\\n", "\n")
if not firebase_admin._apps:
    cred = credentials.Certificate(svc_acct)
    firebase_admin.initialize_app(cred)
db = firestore.client()

pb_cfg        = st.secrets["firebase"]
_pyfb         = pyrebase.initialize_app(pb_cfg)
client_auth   = _pyfb.auth()

auth = client_auth
