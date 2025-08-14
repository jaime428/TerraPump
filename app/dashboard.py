APP_VERSION = "0.57"
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
    slugify,
    fetch_exercise_library,
    fetch_attachments,
    resolve_default_wt,
    build_stats_key,
    load_exercise_stats,
    slug_variants,
    brand_id_from_display,
    _fmt_rep,
    _fmt_wt
)
from app.firebase_config import db, auth


@st.cache_data(ttl=3600)
def get_entries_cached(uid: str):
    return fetch_all_entries(uid)

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

    # ——————— Restore saved workout (if any) ———————
    if "workout_started" not in st.session_state:
        st.session_state.workout_started = False

    if "workout_log" not in st.session_state:
        user_ref = db.collection("users").document(st.session_state.user["uid"])
        doc = user_ref.get()
        active_log = doc.to_dict().get("active_log", [])

        if active_log:
            # ✅ Resume saved workout
            st.session_state.workout_log = active_log
            st.session_state.workout_started = True
            st.session_state.workout_start_time = active_log[0].get("start", datetime.datetime.now())
            st.session_state.sets_count = 1
            st.session_state.log_dirty = False
            st.toast("🔁 Resumed saved workout", icon="🔄")
        else:
            st.session_state.workout_log = []
            st.session_state.sets_count = 1

    if "workout_log" not in st.session_state:
        user_ref = db.collection("users").document(st.session_state.user["uid"])
        doc = user_ref.get()
        st.session_state.workout_log = doc.to_dict().get("active_log", [])

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
        st.session_state.setdefault("workout_log", [{"name": "", "start": None}])
        new_name = st.text_input(
            "Workout Name",
            value = st.session_state.workout_log[0]["name"],
            key="workout_name"
        )
        st.session_state.workout_log[0]["name"] = new_name
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
        if ex_type in ("Machine"):
            smith_only = st.checkbox("Only show Smith‐machine exercises", key="smith_only")
            if smith_only:
                filtered_lib = [
                    e for e in filtered_lib
                    if e.get("subtype","").lower() == "smith"
                ]

        ex = ""       
        machine_docs = []
        attach_name = None
        brand_name = None
       

        if ex_type == "Cable":
            # 1️⃣ Cable exercises from your library
            cable_exercises = [e["name"] for e in filtered_lib]
            choice_ex = st.selectbox(
                "Pick cable exercise",
                ["–– pick one ––"] + cable_exercises,
                key="cable_ex"
            )

            if choice_ex != "–– pick one ––":
                ex = choice_ex
                # 2️⃣ Now pull only the attachments
                all_atts   = fetch_attachments()
                cable_atts = [
                    a for a in all_atts
                    if a.get("type","").strip().lower() == "cable"
                ]

                if not cable_atts:
                    st.warning("No cable attachments found.")
                else:
                    att_names = [a["name"] for a in cable_atts]
                    choice_att = st.selectbox(
                        "Select attachment",
                        ["–– pick one ––"] + att_names,
                        key="cable_att"
                    )
                    if choice_att != "–– pick one ––":
                        attach     = next(a for a in cable_atts if a["name"] == choice_att)
                        default_wt = resolve_default_wt(attach, default_wt)
                        machine_docs = ["__cable_selected__"]
                        attach_name = choice_att

        # 4) BRAND + MACHINE selectors (outside the form)
        elif ex_type in ("Machine","Plate-loaded"):
            brands  = [b.id for b in db.collection("brands").stream()]
            display = [b.replace("_"," ").title() for b in brands]
            mapping = dict(zip(display, brands))

            sel_brand = st.selectbox(
                "Select Brand",
                ["–– pick one ––"] + display,
                key="brand_select"
            )  

            machine_docs = []

            if sel_brand != "–– pick one ––":
                bid          = mapping[sel_brand]
                machines_ref = db.collection("brands").document(bid).collection("machines")
                all_machines = list(machines_ref.stream())
                
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
                    default_wt = resolve_default_wt(md, default_wt)
                    brand_name = sel_brand
                    st.info(f"💡 Default starting weight for **{ex}**: {default_wt} lbs")


        # 5) LIBRARY or FREE-TEXT fallback (if no machine chosen)
        if ex_type != "Cable" and not machine_docs and not ex:
            if filtered_lib:
                names  = [e["name"] for e in filtered_lib]
                choice = st.selectbox(
                    "Pick from exercise library",
                    names + ["Other (type your own)"],
                    key="lib_select"
                )
                if choice != "Other (type your own)":
                    ex   = choice
                    item = next(e for e in filtered_lib if e["name"] == ex)
                    lib_subtype = item.get("subtype")


                    # 1️⃣ apply the library’s default
                    default_wt = resolve_default_wt(item, default_wt)

                    # 2️⃣ only override for Machine/Plate-loaded
                    if ex_type in ("Machine", "Plate-loaded"):
                        for b in db.collection("brands").stream():
                            machines_ref = db.collection("brands")\
                                            .document(b.id)\
                                            .collection("machines")
                            mdocs = list(machines_ref
                                        .where("name", "==", ex)
                                        .limit(1)
                                        .stream())
                            if mdocs:
                                md         = mdocs[0].to_dict()
                                default_wt = resolve_default_wt(md, default_wt)
                                brand_name = b.to_dict().get("name", b.id)
                                st.info(f"💡 Overriding with **{brand_name}** default: {default_wt} lbs")
                                break
                    else:
                        # non-machine types just show the library default
                        st.info(f"💡 Default starting weight for **{ex}**: {default_wt} lbs")
            else:
                ex = st.text_input("Exercise name", key="free_ex_name")

        # 6) Stats lookup
        prev_sets = 1
        prev_reps = 8
        prev_wt = default_wt
        prev_reps_left = 8
        prev_reps_right = 8
        prev_wt_left = default_wt
        prev_wt_right = default_wt


        user_id = st.session_state.user["uid"]
        ready = False
        if ex_type == "Cable":
            ready = bool(ex and attach_name)             # need exercise + attachment
        elif ex_type in ("Machine", "Plate-loaded"):
            ready = bool(ex and brand_name)              # need machine(ex) + brand
        else:
            ready = bool(ex)                             # other types: just exercise
        
        if not ready:
            st.info("Pick the exercise (and brand/attachment if applicable) to see previous stats.")
        else:
            stats_key = build_stats_key(ex_type, ex, brand_name, attach_name)

            base_ex = slugify(ex or "")
            legacy_keys = []
            for ex_var in slug_variants(ex or ""):
                # 1) plain exercise (new scheme for non-cable)
                legacy_keys.append(ex_var)
                # 2) old non-cable scheme often had --noattach
                legacy_keys.append(f"{ex_var}--noattach")

                if ex_type in ("Machine", "Plate-loaded"):
                    # brand by display-name (newer)
                    for b_var in slug_variants(brand_name or ""):
                        legacy_keys.append(f"{b_var}--{ex_var}")
                        legacy_keys.append(f"{b_var}--{ex_var}--noattach")

                    # brand by document id (older)
                    b_id = brand_id_from_display(brand_name)
                    if b_id:
                        for b_var in slug_variants(b_id):
                            legacy_keys.append(f"{b_var}--{ex_var}")
                            legacy_keys.append(f"{b_var}--{ex_var}--noattach")

            # Make unique while preserving order
            legacy_keys = list(dict.fromkeys([k for k in legacy_keys if k]))

            stats = load_exercise_stats(db, user_id, stats_key, legacy_fallbacks=legacy_keys)

        # Pull "previous" (last set only) — no averaging
            prev_sets = int(stats.get("prev_sets", stats.get("last_sets", 1)))

            raw_reps = stats.get("prev_reps", stats.get("last_reps", 8))
            if isinstance(raw_reps, list) and raw_reps:
                prev_reps = raw_reps[-1]
            else:
                prev_reps = raw_reps

            raw_wt = stats.get("prev_weight", stats.get("last_weight", default_wt))
            if isinstance(raw_wt, list) and raw_wt:
                prev_wt = raw_wt[-1]
            else:
                prev_wt = raw_wt

            if isinstance(prev_reps, dict):
                prev_reps_left = int(prev_reps.get("left", 8))
                prev_reps_right = int(prev_reps.get("right", 8))
            else:
                prev_reps_left = prev_reps_right = int(prev_reps if isinstance(prev_reps, (int, float)) else 8)

            if isinstance(prev_wt, dict):
                prev_wt_left = float(prev_wt.get("left", default_wt))
                prev_wt_right = float(prev_wt.get("right", default_wt))
            else:
                w = float(prev_wt if isinstance(prev_wt, (int, float)) else default_wt)
                prev_wt_left = prev_wt_right = w

            # ℹ️ Display Previous Stats
            if stats:
                all_sets    = int(stats.get("prev_sets", stats.get("last_sets", 1)))
                all_reps    = stats.get("prev_reps",  stats.get("last_reps",  []))
                all_weights = stats.get("prev_weight", stats.get("last_weight", []))

                # normalize to lists
                if not isinstance(all_reps, list):
                    all_reps = [all_reps]
                if not isinstance(all_weights, list):
                    all_weights = [all_weights]

                # formatters for unilateral dictionaries
                reps_str    = ", ".join(_fmt_rep(r) for r in all_reps)
                weights_str = ", ".join(_fmt_wt(w, default_wt) for w in all_weights or [])

                st.markdown("##### ℹ️ Previous Stats")
                st.write(f"**Sets:** {all_sets}   \n**Reps:** {reps_str}   \n**Weight:** {weights_str} lbs")

            # init session sets default from previous
            st.session_state.setdefault("sets_count", prev_sets)
            
        # 7) Add / Remove Set controls (outside the form)
        c1, c2 = st.columns([1,1])
        if c1.button("➕ Add Set"):
            st.session_state.sets_count += 1
        if c2.button("➖ Remove Set") and st.session_state.sets_count > 1:
            st.session_state.sets_count -= 1

        # 8) Form for Reps / Weights + single submit
        with st.form("exercise_form", clear_on_submit=False):
            reps_list = []
            weight_list = []
            for i in range(1, st.session_state.sets_count + 1):
                
                cm, cw = st.columns([3, 2])
                sm, sr = cm.columns([1, 7])
                sm.markdown(f"**Set {i}**")
                if st.session_state["unilateral"]:
                    left_reps = sr.number_input(
                        "Left reps", 
                        min_value=1,
                        value=int(st.session_state.get(f"reps_left_{i}", prev_reps_left)),
                        step=1,
                        key=f"reps_left_{i}"
                    )
                    right_reps = sr.number_input(
                        "Right reps", 
                        min_value=1,
                        value=int(st.session_state.get(f"reps_right_{i}", prev_reps_right)),
                        step=1, 
                        key=f"reps_right_{i}"
                    )
                    
                    reps_list.append({"left": left_reps, "right": right_reps})
                    left_wt = cw.number_input(
                        "Left weight (lbs)", min_value=0.0,
                        value=float(st.session_state.get(f"weight_left_{i}", prev_wt_left)),
                        step=2.5, key=f"weight_left_{i}"
                    )
                    right_wt = cw.number_input(
                        "Right weight (lbs)", min_value=0.0,
                        value=float(st.session_state.get(f"weight_right_{i}", prev_wt_right)),
                        step=2.5, key=f"weight_right_{i}"
                    )
                    weight_list.append({"left": left_wt, "right": right_wt})
                else:
                    default_r = st.session_state.get(f"reps_{i}", prev_reps)
                    r = sr.number_input(
                        "Reps", 
                        min_value=1,
                        value=int(default_r),
                        step=1, 
                        key=f"reps_{i}"
                    )
                    reps_list.append(r)

                    w = cw.number_input(
                        "Weight (lbs)", min_value=0.0,
                        value=float(st.session_state.get(f"weight_{i}", prev_wt)),
                        step=2.5, key=f"weight_{i}"
                    )
                    weight_list.append(w)

            submit = st.form_submit_button("✔ Add to Workout")
        
        if submit:
            st.session_state.workout_log.append({
                "exercise": ex,
                "attachment" : attach_name,
                "brand" : brand_name,
                "sets":     st.session_state.sets_count,
                "reps":     reps_list,
                "weights":  weight_list,
                "unilateral" : unilateral,
                "logged_at": datetime.datetime.now()
            })
            st.session_state.log_dirty = True

            
            if unilateral:
                last_weight = weight_list[-1]
                last_reps = reps_list[-1]
            else:
                last_weight = weight_list[-1]
                last_reps = reps_list[-1]


            # 3) save into exercise_stats under your user
            user_id = st.session_state.user["uid"]
            if ex_type == "Cable":
                ex_slug = slugify(ex)
                att_slug = slugify(attach_name) if attach_name and attach_name.lower() != "none" else "noattach"
                combined_slug = f"{ex_slug}--{att_slug}"
            elif ex_type in ("Machine", "Plate-loaded") and brand_name:
                brand_slug = slugify(brand_name)
                machine_slug = slugify(ex)
                combined_slug = f"{brand_slug}--{machine_slug}"
            else:
                combined_slug = slugify(ex)

            stats_ref = db.collection("users") \
                .document(user_id) \
                .collection("exercise_stats") \
                .document(combined_slug)

            stats_ref.set({
                "prev_sets":   st.session_state.sets_count,
                "prev_reps": reps_list,
                "prev_weight": weight_list,
                "brand": brand_name,
                "attachment": attach_name,
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)

            st.session_state.sets_count = 1
            st.success(f"Added {ex}: {st.session_state.sets_count} sets (stats updated)")

        # 9) Live log 
        if len(st.session_state.workout_log) > 1:
            st.markdown("#### 💪 Current Workout Log")

            for idx, entry in enumerate(st.session_state.workout_log[1:], start=1):
                brand = entry.get("brand")
                attachment = entry.get("attachment")
                exercise = entry.get("exercise", "Unnamed")
                sets = entry.get("sets", 0)
                reps = entry.get("reps", [])
                weights = entry.get("weights", [])
                unilateral = entry.get("unilateral", False)

                brand_str = f"**Brand:** {brand}" if brand else ""
                attach_str = f"**Attachment:** {attachment}" if attachment and attachment.lower() != "none" else ""

                # 🚀 Start of Card
                with st.container():
                    st.markdown(f"### {exercise}")
                    if brand_str:
                        st.markdown(brand_str)
                    if attach_str:
                        st.markdown(attach_str)
                    st.markdown(f"**Sets:** {sets}")

                    for s in range(sets):
                        if s >= len(reps) or s >= len(weights):
                            continue

                        # 🧠 Unilateral handling
                        rep = reps[s]
                        wt = weights[s]

                        if unilateral and isinstance(rep, dict) and isinstance(wt, dict):
                            st.markdown(
                                f"- Set {s+1}: {wt['left']} lbs / {wt['right']} lbs – "
                                f"{rep['left']} left / {rep['right']} right"
                            )
                        else:
                            rep_str = rep if isinstance(rep, (int, float)) else str(rep)
                            wt_str = wt if isinstance(wt, (int, float)) else str(wt)
                            st.markdown(f"- Set {s+1}: {wt_str} lbs – {rep_str} reps")

                    # ❌ Remove Button
                    if st.button("❌ Remove", key=f"remove_ex_{idx}"):
                        st.session_state.workout_log.pop(idx)
                        st.session_state.log_dirty = True
                        st.rerun()

                    st.markdown("---")

        # 10) Save button
        if st.session_state.get("log_dirty") and len(st.session_state.workout_log) > 1:
            if st.button("💾 Save Workout Progress"):
                user_ref = db.collection("users").document(st.session_state.user["uid"])
                user_ref.update({"active_log": st.session_state.workout_log})
                st.session_state.log_dirty = False
                st.success("Workout log saved!")
        if "last_save" in st.session_state:
            st.caption(f"Last saved at {st.session_state.last_save.strftime('%I:%M %p')}")

        
        # 11) End Workout Button
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
            user_ref = db.collection("users").document(user_id)
            user_ref.update({"active_log": firestore.DELETE_FIELD})
            st.session_state.workout_started = False
            st.session_state.workout_log     = []
            st.rerun()

    # —————————————————————————————————————————
    st.markdown("### Past Workouts")

    user_ref = db.collection("users").document(st.session_state.user["uid"])
    workouts_ref = user_ref.collection("workouts")

    # Get workout docs ordered by start date
    docs = list(workouts_ref.order_by("start", direction=firestore.Query.DESCENDING).stream())

    if not docs:
        st.info("You haven't saved any workouts yet.")
    else:
        data = []
        for d in docs:
            workout = d.to_dict()
            workout["id"] = d.id

            # Convert Firestore timestamp
            raw_start = workout.get("start")
            if raw_start is not None:
                if hasattr(raw_start, "to_datetime"):
                    workout["start"] = raw_start.to_datetime()
                elif isinstance(raw_start, datetime.datetime):
                    workout["start"] = raw_start
                else:
                    st.warning(f"Could not parse start time for workout: {workout.get('title')}")
                    workout["start"] = datetime.datetime.min
            else:
                workout["start"] = datetime.datetime.min

            # Default fallback title
            workout["title"] = workout.get("name", "Workout")
            data.append(workout)

        # Dropdown
        placeholder = "–– pick one ––"
        labels = [placeholder] + [
            f"{w['start'].strftime('%Y-%m-%d')} – {w['title']}" for w in data
        ]

        sel = st.selectbox("Pick a past workout", labels, key="past_wkt")
        if sel != placeholder:
            wk_idx = labels.index(sel) - 1
            workout = data[wk_idx]

            with st.expander("📋 Workout Summary", expanded=True):
                st.markdown(f"**📝 Title:** {workout['title']}")
                st.markdown(f"**🕒 Start:** {workout['start'].strftime('%Y-%m-%d %I:%M %p')}")

                st.markdown("---")
                st.markdown("### 🏋️ Exercises")

                for i, ex in enumerate(workout.get("entries", []), 1):
                    name = ex.get("exercise", "Unnamed")
                    sets = ex.get("sets", 0)
                    reps = ex.get("reps", [])
                    unilateral = ex.get("unilateral", False)
                    brand = ex.get("brand")
                    attachment = ex.get("attachment")

                    brand_str = f" ({brand})" if brand else ""
                    attach_str = f" – {attachment}" if attachment and attachment.lower() != "none" else ""

                    # 📦 Exercise Header
                    st.markdown(f"**{i}. {name}{brand_str}{attach_str}**")
                    st.markdown(f"*Sets:* **{sets}**")

                    # 🧱 Set-by-set Breakdown
                    for s in range(sets):
                        if s >= len(reps):
                            continue
                        rep_info = reps[s]

                        if unilateral and isinstance(rep_info, dict):
                            left = rep_info.get("left", "?")
                            right = rep_info.get("right", "?")
                            st.markdown(f"- Set {s+1}: {left} left / {right} right")
                        else:
                            st.markdown(f"- Set {s+1}: {rep_info} reps")

                    st.markdown("---")

            # Delete workout
            if st.button("🗑️ Delete Workout", key=f"del_workout_{wk_idx}"):
                workouts_ref.document(workout["id"]).delete()
                st.success("Workout deleted.")
                st.rerun()

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
    if st.button("🔄 Refresh Graphs"):
        st.cache_data.clear()
        st.rerun()
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

ADMIN_UID = st.secrets["admin"]["uid"]
def tab_admin(_=None):
    user = st.session_state.get("user")
    if not user or user["uid"] != ADMIN_UID:
        st.error("❌ You don’t have permission to access this page.")
        return
    st.title("🛠️ Admin: Brands & Machines")
    st.markdown("---")
    
    st.subheader("🔍 Existing Brands & Machines")

    # 2) Per-brand expander + dropdown
    st.subheader("Browse by Brand")
    for b in db.collection("brands").stream():
        brand_id   = b.id
        brand_name = b.to_dict().get("name", brand_id)
        machines_ref = db.collection("brands").document(brand_id).collection("machines")
        machines   = list(machines_ref.stream())

        with st.expander(brand_name):
            # — Delete Brand (only if no machines) —
            if st.button(
                "🗑️ Delete Brand",
                key=f"del_brand_{brand_id}",
                help="Remove this brand (only works if there are no machines)"
            ):
                if not machines:
                    db.collection("brands").document(brand_id).delete()
                    st.success(f"Deleted brand {brand_name}")
                    st.rerun()
                else:
                    st.error("Please remove all machines first!")

            if not machines:
                st.write("No machines for this brand.")
                continue

            # — List each machine with Delete + Edit —
            for m in machines:
                mdata        = m.to_dict()
                machine_name = mdata.get("name", m.id)
                mid          = m.id

                cols = st.columns([4, 1, 1])
                default = resolve_default_wt(mdata, "")
                cols[0].markdown(
                    f"**{machine_name}**  \n"
                    f"Type: {mdata.get('type','')}  |  "
                    f"Default: {default} lb"
                )

                # Delete Machine
                if cols[1].button(
                    "🗑️",
                    key=f"del_{brand_id}_{mid}",
                    help="Delete this machine"
                ):
                    machines_ref.document(mid).delete()
                    st.success(f"Deleted {machine_name}")
                    st.rerun()


                # Edit Machine
                if cols[2].button(
                    "✏️",
                    key=f"edit_{brand_id}_{mid}",
                    help="Edit this machine"
                ):
                    with st.form(f"edit_form_{brand_id}_{mid}", clear_on_submit=False):
                        new_name = st.text_input("Machine name", value=machine_name)
                        type_options = ["Machine","Plate-loaded","Cable","Barbell","Dumbbell","Bodyweight"]
                        default_index = type_options.index(mdata.get("type","Machine")) \
                            if mdata.get("type","Machine") in type_options else 0
                        new_type  = st.selectbox("Type", type_options, index=default_index)
                        new_start = st.number_input(
                            "Default starting weight",
                            value=float(mdata.get("default_starting_weight", 0)),
                            min_value=0.0, step=1.0
                        )
                        save = st.form_submit_button("💾 Save changes")

                    if save:
                        machines_ref.document(mid).update({
                            "name": new_name,
                            "type": new_type,
                            "default_starting_weight": new_start
                        })
                        st.success(f"Updated {new_name}")
                        st.rerun()
    st.markdown("---")

    
    # — Add a new Brand —
    st.subheader("Create a new Brand")
    with st.form("brand_form", clear_on_submit=True):
        brand_name = st.text_input("Brand name")
        add_brand  = st.form_submit_button("➕ Add Brand")
    if add_brand:
        if not brand_name:
            st.error("Give your brand a name!")
        else:
            bid = slugify(brand_name)
            try:
                db.collection("brands").document(bid).set({"name": brand_name})
                st.success(f"Brand '{brand_name}' created!")
            except Exception as e:
                st.error(f"Failed to add brand: {e}")

    st.markdown("---")

    # — Add a new Machine to an existing Brand —
    st.subheader("Create a new Machine")
    # Fetch existing brands for the dropdown
    brands = list(db.collection("brands").stream())
    brand_choices = {b.to_dict().get("name","<unknown>"): b.id for b in brands}
    sel = st.selectbox("Select Brand", [""] + list(brand_choices.keys()))
    if sel:
        with st.form("machine_form", clear_on_submit=True):
            machine_name    = st.text_input("Machine name")
            machine_type    = st.selectbox("Type", ["Machine","Plate-loaded","Cable","Barbell","Dumbbell","Bodyweight"])
            default_weight  = st.number_input("Default starting weight", min_value=10.0, step=1.0)
            subtype        = st.text_input("Subtype (optional)", help="e.g. smith, angled, lever")
            add_machine     = st.form_submit_button("➕ Add Machine")
        if add_machine:
            if not machine_name:
                st.error("Give your machine a name!")
            else:
                mid = slugify(machine_name)
                payload = {
                    "name":                   machine_name,
                    "type":                   machine_type,
                    "default_starting_weight": default_weight
                }
                if subtype.strip():
                    payload["subtype"] = subtype.strip().lower()
                try:
                    db.collection("brands") \
                    .document(brand_choices[sel]) \
                    .collection("machines") \
                    .document(slugify(machine_name)) \
                    .set(payload)
                    st.success("Machine added!")
                except Exception as e:
                    st.error(f"Failed to add machine: {e}")
    st.markdown("---")
    st.subheader("🏋️ Add to Exercise Library")

    with st.form("exercise_lib_form", clear_on_submit=True):
        ex_name       = st.text_input("Exercise name")
        lib_type      = st.selectbox(
            "Type",
            ["Bodyweight","Barbell","Cable","Dumbbell","Machine","Plate-loaded"], index=4
        )
        default_wt    = st.number_input(
            "Default weight (lbs)", 
            min_value=0.0, step=1.0, value=0.0,
            help="This is the generic fallback if no brand override exists"
        )
        subtype       = st.text_input(
            "Subtype (optional)", 
            help="e.g. smith, compound, isolation — for your own filtering"
        )
        add_to_lib    = st.form_submit_button("➕ Add Exercise")

    if add_to_lib:
        if not ex_name.strip():
            st.error("Give your exercise a name!")
        else:
            slug = slugify(ex_name)
            payload = {
                "name": ex_name,
                "type": lib_type,
                "default_weight" : default_wt
            }
            # only include if non-zero / non-empty
            if subtype.strip():
                payload["subtype"] = subtype.strip().lower()

            try:
                db.collection("exercise_library") \
                .document(slug) \
                .set(payload)
                st.success(f"Exercise '{ex_name}' added to library!")
            except Exception as e:
                st.error(f"Failed to add exercise: {e}")
        st.markdown("---")


def main():
    st.set_page_config(page_title="TerraPump", page_icon=":bar_chart:", layout="wide")
    st.sidebar.caption(f"Version {APP_VERSION}")
    st.markdown("""
        <style>
            /* Sidebar styling */
            [data-testid="stSidebar"] {
                background-color: #111;
                padding-top: 2rem;
            }
            [data-testid="stSidebar"] button {
                background: #222;
                color: #fff;
                margin: 5px 0;
            }
            [data-testid="stSidebar"] button:hover {
                background: #BB0000;
            }

            /* Main content mobile tweaks */
            .block-container {
                padding-top: 1rem;
                padding-bottom: 1rem;
            }
            .element-container {
                margin-bottom: 0.5rem;
            }
            p {
                font-size: 0.95rem;
            }
        </style>
    """, unsafe_allow_html=True)

    # Initialize default page
    st.session_state.setdefault('page','Dashboard & Workout')

    # Auth guard
    if not st.session_state.get('user'):
        hide_sidebar()
        if st.session_state.page != 'signup':
            show_login_page()
        else:
            show_signup_page()
        return
    # Fetch data
    data = get_entries_cached(st.session_state.user['uid'])
    

    # Sidebar navigation
    nav_items = [
        ("🏋️","Dashboard & Workout"),
        ("📋","Entries"),
        ("📈","Graphs"),
        ("🙋","About"),
    ]
    if st.session_state.get("user", {}).get("uid") == ADMIN_UID:
        if st.sidebar.button("🛠️ Admin"):
            st.session_state.page = "Admin"
    for icon, label in nav_items:
        if st.sidebar.button(f"{icon} {label}"):
            st.session_state.page = label

    pages = {
        "Dashboard & Workout": tab_dashboard,
        "Entries":             tab_entries,
        "Graphs":              tab_graphs,
        "About":               tab_about,
        "Admin":               tab_admin
    }
    pages.get(st.session_state.page, tab_dashboard)(data)

if __name__ == "__main__":
    main()
