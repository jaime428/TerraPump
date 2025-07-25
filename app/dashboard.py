APP_VERSION = "0.42"
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import datetime
import pandas as pd
import altair as alt
import numpy as np
from firebase_admin import credentials, firestore
from app.utils import (
    fetch_all_entries,
    get_day_value,
    clear_entry_state,
    hide_sidebar,
    show_login_page,
    show_signup_page,
    get_day_name,
    slugify
)
from app.firebase_config import db, auth

# Cache helper
@st.cache_data
def build_series_dict(df: pd.DataFrame):
    dates = pd.to_datetime(df['Date']).dt.normalize()
    return {
        key: (
            df.assign(_dt=dates)
              .set_index('_dt')[key]
              .pipe(pd.to_numeric, errors='coerce')
        )
        for key in ["Weight", "Calories", "Protein", "Steps"]
    }

# --- Dashboard Tab ---
def tab_dashboard(data: pd.DataFrame):
    # Ensure columns exist
    for key in ["Weight", "Calories", "Protein", "Steps"]:
        if key not in data.columns:
            data[key] = 0
    series = build_series_dict(data)

    # Workout state
    st.session_state.setdefault('workout_log', [])
    st.session_state.setdefault('workout_started', False)
    st.session_state.setdefault('workout_start_time', None)

    # Header
    st.markdown("<h1 style='text-align:center;'>TerraPump</h1>", unsafe_allow_html=True)
    st.markdown("---")

    # Quick stats
    today = series['Weight'].index.max()
    yesterday = today - pd.Timedelta(days=1)
    st.markdown("### Quick Stats")
    cols = st.columns(4)
    labels = ['Weight (lbs)', 'Calories', 'Protein (g)', 'Steps']
    for col, label in zip(cols, labels):
        key = label.split()[0]
        s = series[key].last('7D').replace(0, np.nan).ffill()
        cur = float(get_day_value(s, today))
        prev = float(get_day_value(s, yesterday))
        delta = cur - prev
        col.metric(label, round(cur,1), round(delta,1))
        df_trend = s.reset_index().rename(columns={'_dt':'Date', key:'Value'})
        chart = (
            alt.Chart(df_trend)
            .mark_line(point=True, strokeWidth=2)
            .encode(x='Date:T', y='Value:Q', tooltip=['Date:T','Value:Q'])
            .properties(height=130)
        )
        col.altair_chart(chart, use_container_width=True)

    st.markdown("---")

    # Workout section
    st.markdown("### Workout")
    st.markdown("<div style='background:#222;border-radius:8px; padding:1rem;'>", unsafe_allow_html=True)
    if not st.session_state.workout_started:
        name = st.text_input("Name", value=f"Workout {datetime.date.today()}", key="side_name")
        if st.button("💪 Start Workout", key="side_start"):
            st.session_state.workout_started = True
            st.session_state.workout_start_time = datetime.datetime.now()
            st.session_state.workout_log = [{"name": name, "start": st.session_state.workout_start_time}]
            st.session_state.setdefault("sets_count", 1)
            st.success("Workout started!")
            st.rerun()
    else:
        st.write(f"**Started at:** {st.session_state.workout_start_time:%Y-%m-%d %H:%M}")
        # Exercise form
        ex_type = st.selectbox("Exercise type", ["Bodyweight","Barbell","Cable","Dumbbell","Machine","Plate-loaded"], index=3)
        raw_docs = filtered_docs = []
        default_wt = 0.0
        if ex_type in ("Machine","Plate-loaded"):
            brands = [b.id for b in db.collection("brands").stream()]
            display = [b.replace("_"," ").title() for b in brands]
            mapping = dict(zip(display, brands))
            sel = st.selectbox("Brand", ["–– pick one ––"]+display)
            if sel != "–– pick one ––":
                bid = mapping[sel]
                machines_ref = db.collection("brands").document(bid).collection("machines")
                raw_docs = list(machines_ref.stream())
                dtype = "machine" if ex_type=="Machine" else "plate loaded"
                filtered_docs = [d for d in raw_docs if d.to_dict().get("type")==dtype]

        st.session_state.setdefault("sets_count", 1)
        sets_count = st.session_state.sets_count
        with st.form("exercise_form", clear_on_submit=False):
            if filtered_docs:
                ids = [d.id for d in filtered_docs]
                names = [d.to_dict().get("name","<no name>") for d in filtered_docs]
                idx = st.selectbox("Select machine", options=list(range(len(names))), format_func=lambda i: names[i])
                ex = names[idx]
                md = machines_ref.document(ids[idx]).get().to_dict()
                default_wt = md.get("default_starting_weight", md.get("default_weight",0.0))
                st.info(f"💡 Default starting weight for **{ex}**: {default_wt} lbs")
            else:
                ex = st.text_input("Exercise name", key="free_ex_name")
            if ex:
                slug = slugify(ex)
                stats_doc = db.collection("users").document(st.session_state.user["uid"]).collection("exercise_stats").document(slug).get()
                stats = stats_doc.to_dict() if stats_doc.exists else {}
            else:
                stats = {}
            last_sets = stats.get("last_sets",1)
            last_reps = stats.get("last_reps",8)
            last_wt = stats.get("last_weight",default_wt)
            st.session_state.setdefault("sets_count", last_sets)
            reps_list, weight_list = [], []
            for i in range(1, sets_count+1):
                cm, cw = st.columns([3,2])
                sm, sr = cm.columns([1,7])
                sm.markdown(f"**Set {i}**")
                r = sr.number_input("Reps", min_value=1, value=st.session_state.get(f"reps_{i}",last_reps), step=1, key=f"reps_{i}")
                w = cw.number_input("Weight (lbs)", min_value=0.0, value=st.session_state.get(f"weight_{i}",last_wt), step=1.0, key=f"weight_{i}")
                reps_list.append(r); weight_list.append(w)
            b1,b2,b3 = st.columns(3)
            add_set = b1.form_submit_button("➕ Add Set")
            rem_set = b2.form_submit_button("➖ Remove Set")
            submit = b3.form_submit_button("✔ Add to Workout")
        if add_set:
            st.session_state.sets_count += 1
            st.rerun()
        elif rem_set and st.session_state.sets_count>1:
            st.session_state.sets_count -= 1
            st.rerun()
        elif submit:
            st.session_state.workout_log.append({
                "exercise": ex,
                "sets": sets_count,
                "reps": reps_list,
                "weights": weight_list,
                "logged_at": datetime.datetime.now()
            })
            st.success(f"Added {ex}: {sets_count} sets")
        if len(st.session_state.workout_log)>1:
            st.markdown("#### Current Workout Log")
            st.table(pd.DataFrame(st.session_state.workout_log[1:]))
        if st.button("🏁 End Workout", key="side_end"):
            user_id = st.session_state.user["uid"]
            start = st.session_state.workout_start_time
            entries = st.session_state.workout_log[1:]
            db.collection("users").document(user_id).collection("workouts").document(start.isoformat()).set({
                "name": st.session_state.workout_log[0]["name"],
                "start": start,
                "entries": entries,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            st.success("✅ Workout saved!")
            st.session_state.workout_started=False
            st.session_state.workout_log=[]
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("---")

# --- Entries Tab ---
def tab_entries(_):
    st.title("Add or Edit Entries")
    st.markdown("---")
    user = st.session_state.get("user")
    if not user:
        st.warning("Log in to view this page.")
        return
    user_id = user["uid"]
    try:
        docs = db.collection("users").document(user_id).collection("entries").stream()
        df = pd.DataFrame([doc.to_dict()|{"doc_id":doc.id} for doc in docs])
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return
    for col in ["Date","Weight","Calories","Protein","Carbs","Fats","Steps","Training","Cardio"]:
        if col not in df.columns:
            df[col]=np.nan
    df["DateNorm"] = pd.to_datetime(df["Date"],errors="coerce").dt.normalize()
    form_date = st.date_input("Date", value=datetime.date.today(), on_change=clear_entry_state)
    row = df[df["DateNorm"].dt.date==form_date]
    exists = not row.empty
    data = row.iloc[0].to_dict() if exists else {}
    st.subheader(f"{'Edit' if exists else 'Add'} Entry for {form_date}")
    def s_int(k): return int(data.get(k,0) or 0)
    weight_def = float(data.get("Weight") or 0)
    sleep = float(data.get("SleepHours") or 0)
    h,m = int(sleep), int(round((sleep-int(sleep))*60))
    with st.form("entry_form"):
        weight = st.number_input("Weight", value=weight_def, min_value=0.0)
        sleep_h = st.number_input("Sleep Hours", value=h, max_value=24)
        sleep_m = st.number_input("Sleep Minutes", value=m, max_value=59)
        c1,c2,c3,c4 = st.columns(4)
        calories = c1.number_input("Calories", value=s_int("Calories"))
        protein  = c2.number_input("Protein (g)", value=s_int("Protein"))
        carbs    = c3.number_input("Carbs (g)", value=s_int("Carbs"))
        fats     = c4.number_input("Fats (g)", value=s_int("Fats"))
        s1,s2,s3 = st.columns(3)
        steps    = s1.number_input("Steps", value=s_int("Steps"))
        training = s2.text_input("Training", value=str(data.get("Training","")))
        cardio   = s3.number_input("Cardio (mins)", value=s_int("Cardio"))
        submit   = st.form_submit_button("Save Entry")
    if submit:
        payload = {
            "Date":      str(form_date),
            "SleepHours": round(sleep_h+sleep_m/60,2),
            "Calories":  calories,
            "Protein":   protein,
            "Carbs":     carbs,
            "Fats":      fats,
            "Steps":     steps,
            "Training":  training,
            "Cardio":    cardio,
            "email":     user.get("email"),
            "created_at": firestore.SERVER_TIMESTAMP,
            "timestamp":  firestore.SERVER_TIMESTAMP,
            "Weight":    weight
        }
        try:
            db.collection("users").document(user_id).collection("entries").document(str(form_date)).set(payload)
            st.success(f"Entry {'updated' if exists else 'added'}!")
        except Exception as e:
            st.error(f"Save failed: {e}")
    st.markdown("---")

# --- Graphs and About unchanged; omitted for brevity ---

def main():
    st.set_page_config(page_title="TerraPump", page_icon=":bar_chart:", layout="wide")
    st.sidebar.caption(f"Version {APP_VERSION}")
    st.markdown("""
        <style>
        [data-testid="stSidebar"] {background-color:#111; padding-top:2rem;}
        [data-testid="stSidebar"] button {background:#222; color:#fff; margin:5px 0;}
        [data-testid="stSidebar"] button:hover {background:#BB0000;}
        </style>
    """, unsafe_allow_html=True)

    # Initialize default page
    st.session_state.setdefault('page','Dashboard & Workout')

    # Auth guard
    if not st.session_state.get('user'):
        hide_sidebar()
        return show_login_page() if st.session_state.page!='signup' else show_signup_page()

    # Fetch data
    data = fetch_all_entries(st.session_state.user['uid'])

    # Sidebar navigation
    for icon,label in [("🏋️","Dashboard & Workout"),("📋","Entries"),("📈","Graphs"),("🙋","About")]:
        if st.sidebar.button(f"{icon} {label}"):
            st.session_state.page = label

    pages = {
        "Dashboard & Workout": tab_dashboard,
        "Entries": tab_entries,
        "Graphs": tab_graphs,
        "About": tab_about
    }
    pages.get(st.session_state.page, tab_dashboard)(data)

if __name__ == "__main__":
    main()
