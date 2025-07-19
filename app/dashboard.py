import streamlit as st
import datetime
import pandas as pd
import altair as alt
import numpy as np
import firebase_admin
from firebase_admin import credentials
from app.utils import (
    fetch_all_entries,
    get_day_value,
    clear_entry_state,
    hide_sidebar,
    show_login_page,
    show_signup_page,
    get_day_name
)

from app.firebase_config import db, auth


# ✅ Initialize Firebase Admin SDK using Streamlit secrets
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)


# --- Dashboard Tab ---
def tab_dashboard(data: pd.DataFrame):
    # Workout state initialization
    st.session_state.setdefault('workout_log', [])
    st.session_state.setdefault('workout_started', False)
    st.session_state.setdefault('workout_start_time', None)

    # Header
    st.markdown("<h1 style='text-align:center;'>TerraPump (Beta v0.2)</h1>", unsafe_allow_html=True)
    st.markdown("---")

    # Prepare series
    series = build_series_dict(data)
    dates = series['Weight'].index
    today = dates.max()
    yesterday = today - pd.Timedelta(days=1)

    # Quick Stats
    st.markdown("### Quick Stats")
    cols = st.columns(4)
    labels = ['Weight (lbs)', 'Calories', 'Protein (g)', 'Steps']

    for col, label in zip(cols, labels):
        key = label.split()[0]
        s = series[key].last('7D').replace(0, np.nan).ffill()

        cur   = get_day_value(s, today)
        prev  = get_day_value(s, yesterday)
        cur_v = float(cur)
        prev_v= float(prev)
        delta = cur_v - prev_v
        disp  = round(cur_v, 1)
        col.metric(label, disp, round(delta, 1))

        # build a 2-col DataFrame so Altair knows your x/y
        df_trend = (
            s.reset_index()
            .rename(columns={'_dt':'Date', key:'Value'})
        )

        chart = (
            alt.Chart(df_trend)
            .mark_line(point=True, strokeWidth=2)
            .encode(
                x=alt.X('Date:T', title=None),
                y=alt.Y('Value:Q', title=None),
                tooltip=[
                    alt.Tooltip('Date:T', title='Date'),
                    alt.Tooltip('Value:Q', title=label)
                ]
            )
            .properties(height=130)
            # **no** .interactive() so panning/zoom is off
        )

        col.altair_chart(chart, use_container_width=True)


    st.markdown("---")

    st.markdown("### Workout")
    st.markdown("<div style='background:#222;border-radius:8px; padding:1rem;'>", unsafe_allow_html=True)

    if not st.session_state.workout_started:
        name = st.text_input("Name", value=f"Workout {datetime.date.today()}", key="side_name")
        if st.button("💪 Start Workout", key="side_start"):
            st.session_state.workout_started     = True
            st.session_state.workout_start_time  = datetime.datetime.now()
            st.session_state.workout_log         = [{"name": name, "start": st.session_state.workout_start_time}]
            st.session_state.setdefault("sets_count", 1)
            st.success("Workout started!")
            st.rerun()

    else:
        st.write(f"**Started at:** {st.session_state.workout_start_time:%Y-%m-%d %H:%M}")

        # 1) Pick exercise type → determine `ex`
        ex_type = st.selectbox("Exercise type",
            ["Bodyweight","Barbell","Dumbbell","Machine","Plate-loaded"], index=3)

        ex = ""
        default_wt = 0.0
        raw_docs = filtered_docs = []

        if ex_type in ("Machine","Plate-loaded"):
            brands = [b.id for b in db.collection("brands").stream()]
            display_names = [b.replace("_"," ").title() for b in brands]
            brand_map = dict(zip(display_names, brands))
            sel = st.selectbox("Brand", ["–– pick one ––"] + display_names)
            if sel!="–– pick one ––":
                bid = brand_map[sel]
                machines_ref = db.collection("brands").document(bid).collection("machines")
                raw_docs = list(machines_ref.stream())
                dtype = "machine" if ex_type=="Machine" else "plate loaded"
                filtered_docs = [d for d in raw_docs if d.to_dict().get("type","")==dtype]

        # 2) Inside the form, select machine or free text, then slugify

        st.session_state.setdefault("sets_count", 1)
        sets_count = st.session_state.sets_count
        with st.form("exercise_form", clear_on_submit=False):
            if ex_type in ("Machine","Plate-loaded") and filtered_docs:
                ids   = [d.id for d in filtered_docs]
                names = [d.to_dict().get("name","<no name>") for d in filtered_docs]
                idx = st.selectbox("Select machine", options=list(range(len(names))),
                                format_func=lambda i: names[i])
                doc_id     = ids[idx]
                ex         = names[idx]
                md         = machines_ref.document(doc_id).get().to_dict()
                default_wt = md.get("default_starting_weight", md.get("default_weight",0.0))
                st.info(f"💡 Default starting weight for **{ex}**: {default_wt} lbs")
            else:
                default_wt = 0.0

            # slug & fetch stats
            if ex:
                slug = slugify(ex)
                stats_ref = (
                    db.collection("users")
                    .document(st.session_state.uid)
                    .collection("exercise_stats")
                    .document(slug)
                )
                stats_doc = stats_ref.get()
                stats     = stats_doc.to_dict() if stats_doc.exists else {}
            else:
                stats = {}

            # 3) Dynamic Sets/ Reps / Weight with prefill
            reps_list  = []
            weight_list = []

            last_sets   = stats.get("last_sets", 1)
            last_reps   = stats.get("last_reps", 8)
            last_wt     = stats.get("last_weight", default_wt)

            st.session_state.setdefault("sets_count", last_sets)

            for i in range(1, sets_count+1):
                # top‐level: left = label+reps, right = weight
                col_main, col_weight = st.columns([3,2])

                # inside the left block: label vs. reps
                sub_label, sub_reps = col_main.columns([1,7])
                sub_label.markdown(f"**Set {i}**")
                reps_i = sub_reps.number_input(
                    "Reps",
                    min_value=1,
                    value=st.session_state.get(f"reps_{i}", last_reps),
                    step=1,
                    key=f"reps_{i}"
                )

                # weight stays at top‐level right
                weight_i = col_weight.number_input(
                    "Weight (lbs)",
                    min_value=0.0,
                    value=st.session_state.get(f"weight_{i}", last_wt),
                    step=1.0,
                    key=f"weight_{i}"
                )

                reps_list.append(reps_i)
                weight_list.append(weight_i)


            # (Notes field can be removed/commented out if you want)
            # note = st.text_input("Notes (optional)", key="set_note")

            # 3) Buttons row: Add Set | Remove Set | Add to Workout
            b1, b2, b3 = st.columns([1,1,1])
            add_set    = b1.form_submit_button("➕ Add Set")
            remove_set = b2.form_submit_button("➖ Remove Set")
            submit     = b3.form_submit_button("✔ Add to Workout")

        # 4) Handle button clicks outside the form
        if add_set:
            st.session_state.sets_count += 1
            st.rerun()
        elif remove_set and st.session_state.sets_count > 1:
            st.session_state.sets_count -= 1
            st.rerun()
        elif submit:
            st.session_state.workout_log.append({
                "exercise": ex,
                "sets":     sets_count,
                "reps":     reps_list,
                "weights":  weight_list,
                "logged_at": datetime.datetime.now()
            })
            st.success(f"Added {ex}: {sets_count} sets, reps {reps_list}, weights {weight_list}")

        # 6) Live log
        if len(st.session_state.workout_log) > 1:
            st.markdown("#### Current Workout Log")
            df_log = pd.DataFrame(st.session_state.workout_log[1:])
            st.table(df_log)

        # 7) End Workout → persist full log
        if st.button("🏁 End Workout", key="side_end"):
            user_id     = st.session_state.uid
            start_time  = st.session_state.workout_start_time
            log_entries = st.session_state.workout_log[1:]

            workouts_ref = db.collection("users").document(user_id).collection("workouts")
            doc_id = start_time.isoformat()
            workouts_ref.document(doc_id).set({
                "name":      st.session_state.workout_log[0]["name"],
                "start":     start_time,
                "entries":   log_entries,
                "timestamp": firestore.SERVER_TIMESTAMP
            })

            st.success("✅ Workout saved to Firestore!")
            # clear state
            st.session_state.workout_started = False
            st.session_state.workout_log     = []
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("---")
# --- Entries Tab ---
def tab_entries(_):
    st.title("Add or Edit Entries")
    st.markdown("---")
    user_id = st.session_state.uid
    if not user_id:
        st.warning("Log in to view this page.")
        return

    # Fetch & normalize
    try:
        docs = db.collection("users").document(user_id).collection("entries").stream()
        df = pd.DataFrame([doc.to_dict() | {"doc_id": doc.id} for doc in docs])
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return

    if not df.empty:
        df["DateNorm"] = pd.to_datetime(df["Date"]).dt.normalize()

    form_date = st.date_input("Date", value=datetime.date.today(), on_change=clear_entry_state)
    row = df[df.get("DateNorm").dt.date == form_date]
    exists = not row.empty
    data = row.iloc[0].to_dict() if exists else {}

    st.subheader(f"{'Edit' if exists else 'Add'} Entry for {form_date}")

    # Parse defaults
    def s_int(k): return int(data.get(k, 0) or 0)
    weight_def = float(data.get("Weight") or 0)
    sleep = float(data.get("SleepHours") or 0)
    h, m = int(sleep), int(round((sleep - int(sleep))*60))

    with st.form("entry_form"):
        weight = st.number_input("Weight", value=weight_def, min_value=0.0)
        sleep_h = st.number_input("Sleep Hours", value=h, max_value=24)
        sleep_m = st.number_input("Sleep Minutes", value=m, max_value=59)
        c1, c2, c3, c4 = st.columns(4)
        calories = c1.number_input("Calories", value=s_int("Calories"))
        protein  = c2.number_input("Protein (g)", value=s_int("Protein"))
        carbs    = c3.number_input("Carbs (g)", value=s_int("Carbs"))
        fats     = c4.number_input("Fats (g)", value=s_int("Fats"))
        s1, s2, s3 = st.columns(3)
        steps    = s1.number_input("Steps", value=s_int("Steps"))
        training = s2.text_input("Training", value=str(data.get("Training", "")))
        cardio   = s3.number_input("Cardio (mins)", value=s_int("Cardio"))
        submit = st.form_submit_button("Save Entry")

    if submit:
        payload = {
            "Date": str(form_date),
            "SleepHours": round(sleep_h + sleep_m/60, 2),
            "Calories": calories,
            "Protein": protein,
            "Carbs": carbs,
            "Fats": fats,
            "Steps": steps,
            "Training": training,
            "Cardio": cardio,
            "timestamp": firestore.SERVER_TIMESTAMP
        }
        if weight > 0: payload["Weight"] = weight
        date_id = str(form_date)
        try:
            db.collection("users").document(user_id).collection("entries").document(date_id).set(payload)
            st.success(f"Entry {'updated' if exists else 'added'}!")
        except Exception as e:
            st.error(f"Save failed: {e}")
    st.markdown("---")

# --- Graphs Tab ---
def tab_graphs(data: pd.DataFrame):
    st.title("Insights & Calendar")
    st.markdown("---")

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
def tab_about(data):
    st.title("About Me")
    st.markdown("---")
    st.write("Hello")

# --- Main ---
def main():
    # Page config & sidebar styling
    st.set_page_config(page_title="TerraPump", page_icon=":bar_chart:", layout="wide")
    st.markdown("""
        <style>
        [data-testid="stSidebar"] {background-color:#111; padding-top:2rem;}
        [data-testid="stSidebar"] button {background:#222; color:#fff; margin:5px 0;}
        [data-testid="stSidebar"] button:hover {background:#BB0000;}
        </style>
    """, unsafe_allow_html=True)

    # Auth guard
    if st.session_state.get("force_logout", False):
        st.session_state.clear(); st.rerun()
    if 'logged_in' not in st.session_state:
        st.session_state.update({'logged_in':False,'uid':None,'page':'Dashboard & Workout'})

    if not st.session_state.logged_in:
        hide_sidebar()
        return show_login_page() if st.session_state.page!="signup" else show_signup_page()

    # Data
    # Data
    try:
        data = fetch_all_entries(st.session_state.uid)
    except Exception as e:
        st.error(f"❌ Failed to fetch entries: {e}")
        return


    # Sidebar navigation
    st.sidebar.title("TerraPump")
    for icon,label in [("🏋️","Dashboard & Workout"),("📋","Entries"),("📈","Graphs"),("🙋","About")]:
        if st.sidebar.button(f"{icon} {label}"):
            st.session_state.page = label

    # Route to tab
    pages = {
        "Dashboard & Workout": tab_dashboard,
        "Entries": tab_entries,
        "Graphs": tab_graphs,
        "About": tab_about
    }
    pages.get(st.session_state.page, tab_dashboard,)(data)

if __name__ == "__main__":
    main()