APP_VERSION = "0.5"
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import datetime
import pandas as pd
import altair as alt
import numpy as np
from firebase_admin import firestore
from app.utils import (
    fetch_all_entries,
    get_day_value,
    clear_entry_state,
    hide_sidebar,
    show_login_page,
    show_signup_page,
    get_day_name,
    slugify,
    fetch_exercise_library,
    fetch_attachments
)
from app.firebase_config import db, auth

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

def tab_dashboard(data: pd.DataFrame):
    # Ensure data columns
    for key in ["Weight", "Calories", "Protein", "Steps"]:
        if key not in data.columns:
            data[key] = 0
    series = build_series_dict(data)

    # Workout state defaults
    st.session_state.setdefault('workout_log', [])
    st.session_state.setdefault('workout_started', False)
    st.session_state.setdefault('workout_start_time', None)
    st.session_state.setdefault('sets_count', 1)

    # Header + Quick Stats (unchanged)
    st.markdown("<h1 style='text-align:center;'>TerraPump</h1>", unsafe_allow_html=True)
    st.markdown("---")
    today = series['Weight'].index.max()
    yesterday = today - pd.Timedelta(days=1)
    st.markdown("### Quick Stats")
    cols = st.columns(4)
    labels = ['Weight (lbs)', 'Calories', 'Protein (g)', 'Steps']
    for col, label in zip(cols, labels):
        key = label.split()[0]
        s = series[key].last('7D').replace(0, np.nan).ffill()
        cur  = float(get_day_value(s, today))
        prev = float(get_day_value(s, yesterday))
        col.metric(label, round(cur,1), round(cur-prev,1))
        df_trend = s.reset_index().rename(columns={'_dt':'Date', key:'Value'})
        chart = (
            alt.Chart(df_trend)
               .mark_line(point=True, strokeWidth=2)
               .encode(
                   x='Date:T', y='Value:Q',
                   tooltip=['Date:T','Value:Q']
               )
               .properties(height=200)
        )
        col.altair_chart(chart, use_container_width=True)
    st.markdown("---")

    # —————————————————————————————————————————
    st.markdown("### Workout")
    st.markdown("<div style='background:#222;border-radius:8px; padding:1rem;'>", unsafe_allow_html=True)

    if not st.session_state.workout_started:
        name = st.text_input(
            "Name",
            value=f"Workout {datetime.date.today()}",
            key="side_name"
        )
        if st.button("💪 Start Workout", key="side_start"):
            st.session_state.workout_started    = True
            st.session_state.workout_start_time = datetime.datetime.now()
            st.session_state.workout_log        = [{"name": name, "start": st.session_state.workout_start_time}]
            st.session_state.sets_count         = 1
            st.success("Workout started!")
            st.rerun()

    else:
        st.write(f"**Started at:** {st.session_state.workout_start_time:%Y-%m-%d %H:%M}")

        # 1) Exercise type
        ex_type    = st.selectbox(
            "Exercise type",
            ["Bodyweight","Barbell","Cable","Dumbbell","Machine","Plate-loaded"],
            index=3,
            key="exercise_type"
        )

        st.session_state.setdefault("unilateral", False)
        unilateral = st.checkbox(
            "Unilateral exercise? (separate left/right reps & weights)",
            value=st.session_state["unilateral"],
            key="unilateral"
        )

        sets_count = st.session_state.sets_count
        

        # 2) Default weight for pure Barbell
        type_defaults = {"Barbell": 45.0}
        default_wt    = type_defaults.get(ex_type, 0.0)

        # 3) Library fallback prep
        library     = fetch_exercise_library()
        type_key    = ex_type.lower().replace("-", "").replace(" ", "")
        filtered_lib = [
            e for e in library
            if e.get("type","").lower().replace(" ", "") == type_key
        ]

        ex = ""       
        machine_docs = []
       

        if ex_type == "Cable":
            # Pull all attachments, then filter to only type “Cable”
            all_atts   = fetch_attachments()
            cable_atts = [a for a in all_atts if a.get("type","").strip().lower()=="cable"]
            if not cable_atts:
                st.warning("No cable attachments found.")
                machine_docs = []  # fallback back to library/text
            else:
                names = [a.get("name","<no name>") for a in cable_atts]
                sel   = st.selectbox("Attachment", ["–– pick one ––"] + names, key="cable_select")

                if sel != "–– pick one ––":
                    attach     = next(a for a in cable_atts if a["name"] == sel)
                    ex         = attach["name"]                          # 📌 set the exercise
                    default_wt = attach.get("default_weight", default_wt)  # 📌 override default

                # block out the other fallbacks
                machine_docs = ["__cable_selected__"]

        # 4) BRAND + MACHINE selectors (outside the form)
        elif ex_type in ("Machine","Plate-loaded"):
            brands  = [b.id for b in db.collection("brands").stream()]
            display = [b.replace("_"," ").title() for b in brands]
            mapping = dict(zip(display, brands))

            sel_brand = st.selectbox(
                "Brand",
                ["–– pick one ––"] + display,
                key="brand_select"
            )
            if sel_brand != "–– pick one ––":
                bid          = mapping[sel_brand]
                machines_ref = db.collection("brands").document(bid).collection("machines")
                all_machines = list(machines_ref.stream())

                # match Firestore type → UI type via slugify
                slug_type    = slugify(ex_type)
                machine_docs = [
                    d for d in all_machines
                    if slugify(d.to_dict().get("type","")) == slug_type
                ]

                if machine_docs:
                    names       = [d.to_dict().get("name","<no name>") for d in machine_docs]
                    sel_name    = st.selectbox("Machine", names, key="machine_select")
                    idx         = names.index(sel_name)
                    selected    = machine_docs[idx]
                    ex          = sel_name
                    md          = machines_ref.document(selected.id).get().to_dict()
                    default_wt  = md.get("default_starting_weight",
                                        md.get("default_weight", default_wt))
                    st.info(f"💡 Default starting weight for **{ex}**: {default_wt} lbs")

        # 5) LIBRARY or FREE-TEXT fallback (if no machine chosen)
        if not machine_docs:
            if filtered_lib:
                names  = [e["name"] for e in filtered_lib]
                choice = st.selectbox(
                    "Pick from exercise library",
                    names + ["Other (type your own)"],
                    key="lib_select"
                )
                if choice != "Other (type your own)":
                    ex         = choice
                    item       = next(e for e in filtered_lib if e["name"]==ex)
                    default_wt = item.get("default_weight", default_wt)
                    st.info(f"💡 Default starting weight for **{ex}**: {default_wt} lbs")
            else:
                ex = st.text_input("Exercise name", key="free_ex_name")

        # 6) Stats lookup
        if ex:
            slug      = slugify(ex)
            stats_doc = (
                db.collection("users")
                  .document(st.session_state.user["uid"])
                  .collection("exercise_stats")
                  .document(slug)
                  .get()
            )
            stats     = stats_doc.to_dict() if stats_doc.exists else {}
        else:
            stats = {}

        last_sets = stats.get("last_sets", 1)
        last_reps = stats.get("last_reps", 8)
        last_wt   = stats.get("last_weight", default_wt)
        st.session_state.setdefault("sets_count", last_sets)

        # 7) Form for Reps / Weights / Buttons

        with st.form("exercise_form", clear_on_submit=False):
            reps_list = []
            weight_list = []
            for i in range(1, sets_count + 1):
                cm, cw = st.columns([3, 2])
                sm, sr = cm.columns([1, 7])
                sm.markdown(f"**Set {i}**")
                if st.session_state["unilateral"]:
                    left_reps = sr.number_input(
                        "Left reps", min_value=1,
                        value=st.session_state.get(f"reps_left_{i}", last_reps),
                        step=1, key=f"reps_left_{i}"
                    )
                    right_reps = sr.number_input(
                        "Right reps", min_value=1,
                        value=st.session_state.get(f"reps_right_{i}", last_reps),
                        step=1, key=f"reps_right_{i}"
                    )
                    reps_list.append({"left": left_reps, "right": right_reps})
                    left_wt = cw.number_input(
                        "Left weight (lbs)", min_value=0.0,
                        value=float(st.session_state.get(f"weight_left_{i}", last_wt)),
                        step=1.0, key=f"weight_left_{i}"
                    )
                    right_wt = cw.number_input(
                        "Right weight (lbs)", min_value=0.0,
                        value=float(st.session_state.get(f"weight_right_{i}", last_wt)),
                        step=1.0, key=f"weight_right_{i}"
                    )
                    weight_list.append({"left": left_wt, "right": right_wt})
                else:
                    r = sr.number_input(
                        "Reps", min_value=1,
                        value=st.session_state.get(f"reps_{i}", last_reps),
                        step=1, key=f"reps_{i}"
                    )
                    reps_list.append(r)
                    w = cw.number_input(
                        "Weight (lbs)", min_value=0.0,
                        value=float(st.session_state.get(f"weight_{i}", last_wt)),
                        step=1.0, key=f"weight_{i}"
                    )
                    weight_list.append(w)

            b1, b2, submit = st.columns(3)

            b1        = st.form_submit_button("➕ Add Set")
            b2        = st.form_submit_button("➖ Remove Set")
            submit    = st.form_submit_button("✔ Add to Workout")

        # 8) Handle buttons
        if b1:
            st.session_state.sets_count += 1
            st.rerun()
        elif b2 and st.session_state.sets_count > 1:
            st.session_state.sets_count -= 1
            st.rerun()
        elif submit:
            st.session_state.workout_log.append({
                "exercise": ex,
                "sets":     sets_count,
                "reps":     reps_list,
                "weights":  weight_list,
                "unilateral" : unilateral,
                "logged_at": datetime.datetime.now()
            })
            st.success(f"Added {ex}: {sets_count} sets")
            st.rerun()

        # 9) Live log + End button
        if len(st.session_state.workout_log) > 1:
            st.markdown("#### Current Workout Log")

            display_log = []
            for entry in st.session_state.workout_log[1:]:
                reps = entry["reps"]
                if all(isinstance(r, dict) for r in reps):
                    reps_str = "  ".join(f"{r['left']}/{r['right']}" for r in reps)
                else:
                    reps_str = "  ".join(str(r) for r in reps)

                weights = entry["weights"]
                if all(isinstance(w, dict) for w in weights):
                    wt_str = "  ".join(f"{w['left']}/{w['right']}" for w in weights)
                else:
                    wt_str = "  ".join(str(w) for w in weights)

                display_log.append({
                    "Exercise":  entry["exercise"],
                    "Sets":      entry["sets"],
                    "Reps":      reps_str,
                    "Weights":   wt_str,
                    "Logged At": entry["logged_at"].strftime("%Y-%m-%d %H:%M"),
                })

            df_display = pd.DataFrame(display_log)
            st.table(df_display)

        if st.button("🏁 End Workout", key="side_end"):
            user_id = st.session_state.user["uid"]
            start   = st.session_state.workout_start_time
            entries = st.session_state.workout_log[1:]
            db.collection("users") \
              .document(user_id) \
              .collection("workouts") \
              .document(start.isoformat()) \
              .set({
                  "name":      st.session_state.workout_log[0]["name"],
                  "start":     start,
                  "entries":   entries,
                  "timestamp": firestore.SERVER_TIMESTAMP
              })
            st.success("✅ Workout saved!")
            st.session_state.workout_started = False
            st.session_state.workout_log     = []
            st.rerun()

    # —————————————————————————————————————————
    st.markdown("---")
    st.markdown("### Past Workouts")
    user_id = st.session_state.user["uid"]
    workouts_ref = (
        db.collection("users")
        .document(user_id)
        .collection("workouts")
    )
    
    docs = list(workouts_ref.order_by("start", direction=firestore.Query.DESCENDING).stream())
    if not docs:
        st.info("You haven't saved any workouts yet.")
    else:
        # build a picklist of "Workout name (YYYY-MM-DD HH:MM)"
        placeholder = "Select a workout..."
        labels = [placeholder]
        data = [None]
        for doc in docs:
            w = doc.to_dict()
            ts = w["start"]  # this is a Python datetime
            labels.append(f"{w['name']} ({ts:%Y-%m-%d %H:%M})")
            data.append(w)

        sel = st.selectbox("", labels, index=0, key="past_wkt")
        if sel!= placeholder:
            workout = data[labels.index(sel)]

        # turn its entries into a display table
            rows = []
            for e in workout["entries"]:
                # format reps
                r = e["reps"]
                if all(isinstance(x, dict) for x in r):
                    reps_str = "  ".join(f"{x['left']}/{x['right']}" for x in r)
                else:
                    reps_str = "  ".join(str(x) for x in r)
                # format weights
                wts = e["weights"]
                if all(isinstance(x, dict) for x in wts):
                    wt_str = "  ".join(f"{x['left']}/{x['right']}" for x in wts)
                else:
                    wt_str = "  ".join(str(x) for x in wts)

                rows.append({
                    "Exercise":   e["exercise"],
                    "Sets":       e["sets"],
                    "Reps":       reps_str,
                    "Weights":    wt_str,
                    "Logged At":  e["logged_at"].strftime("%Y-%m-%d %H:%M"),
                })

            df_past = pd.DataFrame(rows)
            st.table(df_past)
    # — end Past Workouts —
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
            "timestamp":  firestore.SERVER_TIMESTAMP,
            "Weight":    weight
        }
        try:
            db.collection("users").document(user_id).collection("entries").document(str(form_date)).set(payload)
            st.success(f"Entry {'updated' if exists else 'added'}!")
        except Exception as e:
            st.error(f"Save failed: {e}")
    st.markdown("---")

# --- Graphs Tab ---
def tab_graphs(data: pd.DataFrame):
    st.title("Insights & Calendar")
    st.markdown("---")

    for key in ["Weight", "Calories", "Protein", "Steps"]:
        if key not in data.columns:
            data[key] = 0

    if data.empty or "Date" not in data.columns:
        st.info("No data yet. Use the Entries tab to log your first workout or daily stats.")
        st.markdown("---")
        return
    
    # Weight over time
    wdf = data.assign(
        DateNorm=pd.to_datetime(data['Date']).dt.normalize(),
        Weight=pd.to_numeric(data['Weight'], errors='coerce').replace(0, np.nan)
    ).dropna(subset=['Weight'])

    if wdf.empty:
        st.write("No weight data to display.")
    else:
        mn, mx = wdf['Weight'].min(), wdf['Weight'].max()
        pad = (mx - mn) * 0.05
        base = alt.Chart(wdf).encode(x='DateNorm:T')
        line = base.mark_line(point=True, strokeWidth=3, color='#DA1A32').encode(
            y=alt.Y('Weight:Q', scale=alt.Scale(domain=[max(mn-pad,0), mx+pad]))
        )
        mean_rule = alt.Chart(pd.DataFrame({'mean':[wdf['Weight'].mean()]})).mark_rule(strokeDash=[4,4]).encode(y='mean:Q')
        st.altair_chart((line+mean_rule).properties(width=700, height=350), use_container_width=True)
    st.markdown("---")

    # Training calendar
    data['DateNorm'] = pd.to_datetime(data['Date']).dt.normalize()
    df_dates = data[['DateNorm','Training']].drop_duplicates()
    all_days = pd.DataFrame({'DateNorm': pd.date_range(data['DateNorm'].min(), data['DateNorm'].max(), freq='D')})
    calendar_df = all_days.merge(df_dates, on='DateNorm', how='left').fillna({'Training':'Rest'})
    calendar_df['Type'] = calendar_df['Training'].apply(lambda x: 'Rest' if x=='Rest' else 'Workout')
    calendar_df['Week'] = calendar_df['DateNorm'].dt.isocalendar().week
    calendar_df['Day']  = calendar_df['DateNorm'].dt.day_name().str[:3]

    cal = alt.Chart(calendar_df).mark_rect().encode(
        x=alt.X('Day:O', sort=['Mon','Tue','Wed','Thu','Fri','Sat','Sun']),
        y='Week:O',
        color=alt.Color('Type:N', scale=alt.Scale(domain=['Rest','Workout'], range=['#1E90FF','#DA1A32'])),
        tooltip=['DateNorm:T','Training:N']
    ).properties(width=700, height=250)
    st.altair_chart(cal, use_container_width=True)
    st.markdown("---")

# --- About Tab ---
def tab_about(_=None):
    st.title("👨‍💻 About the Developer")
    st.markdown("---")
    st.markdown(
         """
        ### Jaime Cruz
        **Sophomore @ University of Maryland**  
        Studying **Information Science**, passionate about building useful tools for fitness and student productivity.

         #### 🔧 About TerraPump
        TerraPump is a personal fitness tracker designed for students and gym-goers.  
        It helps track daily stats like weight, calories, steps, and workouts – with Firebase-backed authentication and real-time data.

        #### 🌐 Links
        - [GitHub](https://github.com/jaime428)
        - [LinkedIn](https://www.linkedin.com/in/jaimecruz428/)

        _Thanks for checking out my project!_
        """
    )

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
