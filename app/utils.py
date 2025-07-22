import streamlit as st
import datetime
import pandas as pd
import re

from .firebase_config import auth, db

# --- Sidebar Styling ---

def hide_sidebar():
    st.markdown("""
        <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
        </style>
    """, unsafe_allow_html=True)

# --- Login UI ---

def show_login_page():
    st.title("Login")
    email = st.text_input("Email", key="login_email")
    pw = st.text_input("Password", type="password", key="login_password")

    if st.button("Log in"):
        try:
            user = auth.sign_in_with_email_and_password(email, pw)
            st.session_state.user = user
            st.session_state.page = "dashboard"
            st.success("✅ Logged in!")
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {e}")

    if st.button("Sign Up"):
        st.session_state.page = "signup"
        st.rerun()

# --- Signup UI ---

def show_signup_page():
    st.title("Sign Up")
    email = st.text_input("Email", key="signup_email")
    password = st.text_input("Password", type="password", key="signup_password")
    confirm = st.text_input("Confirm Password", type="password", key="signup_confirm")

    if st.button("Create Account"):
        if password != confirm:
            st.error("Passwords do not match.")
        else:
            try:
                user = auth.create_user_with_email_and_password(email, password)
                st.success("Account created! Please log in.")
                st.session_state.page = "login"
                st.rerun()
            except Exception as e:
                st.error(f"Signup failed: {e}")

    if st.button("Back to Login"):
        st.session_state.page = "login"
        st.ererun()

# --- Firestore Entry Fetching ---

def fetch_all_entries(uid):
    try:
        docs = db.collection("users").document(uid).collection("entries").stream()
        entries = [doc.to_dict() | {"doc_id": doc.id} for doc in docs]
        if entries:
            return pd.DataFrame(entries)
        else:
            return pd.DataFrame(columns=["Date","Weight","Calories","Protein","Carbs","Fats","Steps","Training","Cardio","doc_id"])
    except Exception as e:
        st.error(f"Error fetching entries: {e}")
        return pd.DataFrame()

# --- Utilities ---

def clear_entry_state():
    for key in list(st.session_state.keys()):
        if key.startswith("entry_"):
            del st.session_state[key]

def slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.strip().lower()).strip('_')

def get_day_value(series, date):
    return series.get(date, 0)

def get_day_name(date_obj):
    if isinstance(date_obj, str):
        date_obj = pd.to_datetime(date_obj)
    return date_obj.strftime("%A")
