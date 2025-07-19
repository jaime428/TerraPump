import streamlit as st
import datetime
import pandas as pd
import re
import pyrebase
import firebase_admin
from firebase_admin import credentials, firestore
from app import firebase_config

# ✅ Initialize Firebase Admin SDK using secrets (not file path)
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)

# ✅ Get Firestore client
db = firestore.client()

# ✅ Initialize pyrebase (client-side auth)
firebase = pyrebase.initialize_app(firebase_config.firebase_config)
auth = firebase.auth()


def hide_sidebar():
    st.markdown(
        """
        <style>
            /* Hide the entire sidebar panel */
            [data-testid="stSidebar"] {
                display: none;
            }
            /* Hide the collapse/expand hamburger */
            [data-testid="collapsedControl"] {
                display: none;
            }
        </style>
        """,
        unsafe_allow_html=True
    )

def hide_sidebar():
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True
    )


def show_login_page():
    st.title("Login")
    
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_password")
    login_btn = st.button("Log In")

    if login_btn:
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state.logged_in = True
            st.session_state.uid = user['localId']
            st.session_state.page = "Dashboard & Workout"
            st.success("Logged in successfully!")
            st.rerun()
        except Exception as e:
            st.error("Login failed. Check your credentials.")

    if st.button("Create an account"):
        st.session_state.page = "signup"
        st.rerun()


def show_signup_page():
    st.title("Sign Up")
    
    email = st.text_input("Email", key="signup_email")
    password = st.text_input("Password", type="password", key="signup_password")
    confirm = st.text_input("Confirm Password", type="password", key="signup_confirm")
    signup_btn = st.button("Sign Up")

    if signup_btn:
        if password != confirm:
            st.error("Passwords do not match.")
        else:
            try:
                user = auth.create_user_with_email_and_password(email, password)
                st.success("Account created! Please log in.")
                st.session_state.page = "Dashboard & Workout"
                st.session_state.logged_in = True
                st.session_state.uid = user['localId']
                st.rerun()
            except Exception as e:
                st.error("Signup failed. Try a different email.")

    if st.button("Back to login"):
        st.session_state.page = "login"
        st.rerun()

def fetch_all_entries(uid):
    try:
        docs = db.collection("users").document(uid).collection("entries").stream()
        entries = [doc.to_dict() | {"doc_id": doc.id} for doc in docs]
        if entries:
            df = pd.DataFrame(entries)
        else:
            columns = ["Date","Weight","Calories","Protein","Carbs","Fats","Steps","Training","Cardio","doc_id"]
            df = pd.DataFrame(columns=columns)
        return df
    except Exception as e:
        st.error(f"Error fetching entries: {e}")
        return pd.DataFrame()


def get_day_value(series, date):
    return series.get(date, 0)

def get_day_name(date_obj):
    if isinstance(date_obj, str):
        date_obj = pd.to_datetime(date_obj)
    return date_obj.strftime("%A")

def clear_entry_state():
    for key in list(st.session_state.keys()):
        if key.startswith("entry_"):
            del st.session_state[key]

def slugify(name: str) -> str:
    """Simplistic slug: lowercase, spaces & non-alphanum → underscore."""
    return re.sub(r'[^a-z0-9]+', '_', name.strip().lower()).strip('_')