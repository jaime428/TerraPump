import streamlit as st
import pandas as pd
import re
from firebase_admin import firestore
from .firebase_config import auth, db

# --- Sidebar Styling ---

def hide_sidebar():
    st.markdown(
        """
        <style>
            [data-testid=\"stSidebar\"] { display: none; }
            [data-testid=\"collapsedControl\"] { display: none; }
        </style>
        """,
        unsafe_allow_html=True
    )

# --- Login UI ---

def show_login_page():
    st.title("Login")
    email = st.text_input("Email", key="login_email")
    pw = st.text_input("Password", type="password", key="login_password")

    if st.button("Login"):
        try:
            user = auth.sign_in_with_email_and_password(email, pw)

            uid = user["localId"]
            email = user.get("email", email)
            
            # --- ensure there’s a users/{uid} doc ---
            user_ref = db.collection("users").document(uid)
            if not user_ref.get().exists:
                user_ref.set({
                    "email":      email,
                    "created_at": firestore.SERVER_TIMESTAMP
                })

            # now store in session_state
            st.session_state.user = {"uid": uid, "email": email}
            st.session_state.page = "Dashboard & Workout"
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
                uid = user["localId"]

                # ✨ Write profile metadata ✨
                db.collection("users").document(uid).set({
                    "email": email,
                    "created_at": firestore.SERVER_TIMESTAMP
                })

                st.success("Account created! Please log in.")
                st.session_state.page = "login"
                st.rerun()
            except Exception as e:
                st.error(f"Signup failed: {e}")

    if st.button("Back to Login"):
        st.session_state.page = "login"
        st.rerun()

# --- Firestore Entry Fetching ---

def fetch_all_entries(uid):
    try:
        docs = db.collection("users").document(uid).collection("entries").stream()
        entries = [doc.to_dict() | {"doc_id": doc.id} for doc in docs]
        if entries:
            return pd.DataFrame(entries)
        else:
            # return empty DataFrame with predefined columns
            return pd.DataFrame(
                columns=[
                    "Date", "Weight", "Calories", "Protein",
                    "Carbs", "Fats", "Steps", "Training",
                    "Cardio", "doc_id"
                ]
            )
    except Exception as e:
        st.error(f"Error fetching entries: {e}")
        return pd.DataFrame()

# --- Utilities ---

def clear_entry_state():
    for key in list(st.session_state.keys()):
        if key.startswith("entry_"):
            del st.session_state[key]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def get_day_value(series, date):
    return series.get(date, 0)


def get_day_name(date_obj):
    if isinstance(date_obj, str):
        date_obj = pd.to_datetime(date_obj)
    return date_obj.strftime("%A")

def fetch_exercise_library():
    docs = db.collection("exercise_library").stream()
    # assume each doc has at least “name” and optionally “default_weight”
    return [doc.to_dict() for doc in docs]

def fetch_attachments():
    docs = db.collection("attachments").stream()
    # each dict will have whatever fields you set in Firestore,
    # e.g. {"name":"EZ Bar","type":"Cable"}
    return [doc.to_dict() for doc in docs]

def resolve_default_wt(item: dict, fallback: float) -> float:
    if "default_starting_weight" in item:
        try:
            return float(item["default_starting_weight"])
        except (TypeError, ValueError):
            return fallback

    if "default_weight" in item:
        try:
            return float(item["default_weight"])
        except (TypeError, ValueError):
            return fallback
    return fallback

def build_stats_key(ex_type: str, ex_name: str, brand_name: str | None, attach_name: str | None) -> str:
    sx = slugify(ex_name or "")
    if ex_type == "Cable":
        sa = slugify(attach_name) if attach_name and attach_name.lower() != "none" else "noattach"
        return f"{sx}--{sa}"
    if ex_type in ("Machine", "Plate-loaded") and brand_name:
        sb = slugify(brand_name)
        return f"{sb}--{sx}"
    return sx

def load_exercise_stats(db, user_id: str, key: str, legacy_fallbacks: list[str] | None = None) -> dict:
    ref = db.collection("users").document(user_id).collection("exercise_stats")
    doc = ref.document(key).get()
    if doc.exists:
        return doc.to_dict() or {}
    for old_key in (legacy_fallbacks or []):
        d = ref.document(old_key).get()
        if d.exists:
            return d.to_dict() or {}
    return {}

def slug_variants(name: str) -> list[str]:
    if not name:
        return []
    n = name.strip().lower()
    hy = n.replace(" ", "-")
    us = n.replace(" ", "_")
    # also strip duplicate separators
    return list(dict.fromkeys([hy, us]))

def brand_id_from_display(display_name: str | None) -> str | None:
    if not display_name:
        return None
    mapping = {b.to_dict().get("name", b.id): b.id for b in db.collection("brands").stream()}
    return mapping.get(display_name) or mapping.get(display_name.title())

def _fmt_rep(rep):
    if isinstance(rep, dict):
        l = rep.get("left", "?")
        r = rep.get("right", "?")
        return f"{l}/{r}"
    return str(rep)

def _fmt_wt(w):
    if isinstance(w, dict):
        l = w.get("left", default_wt)
        r = w.get("right", default_wt)
        # strip .0 for whole numbers
        l = int(l) if isinstance(l, (int, float)) and float(l).is_integer() else l
        r = int(r) if isinstance(r, (int, float)) and float(r).is_integer() else r
        return f"{l}/{r}"
    # strip .0 for whole numbers
    if isinstance(w, (int, float)) and float(w).is_integer():
        return str(int(w))
    return str(w)
