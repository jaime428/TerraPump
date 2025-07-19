# 🏋️ TerraPump

**TerraPump** is a web-based fitness tracking app built with **Streamlit** and **Firebase**, designed to help users log their workouts, track physical progress, and visualize health stats all in one sleek dashboard.

## 📦 Version History

- **v0.4** – Deployed working login, Firestore integration, and dynamic workout tracker. About Me tab added.
- **v0.3** – Streamlit UI overhauled; graphs cleaned up; Firebase structure updated.
- **v0.2** – Form input and entry logging connected to Firestore.
- **v0.1** – Initial Streamlit and Firebase setup with basic form layout.

---

## 🌟 Features

- 🔐 Firebase login (email/password)
- 📅 Log daily metrics (weight, calories, protein, steps, sleep)
- 🏋️ Structured workout tracking (sets, reps, weight, exercise type)
- ⚙️ Machine/equipment selector with default weight autofill
- 📈 Progress charts (with filters and consistent styling)
- 🧠 Smart memory: recalls past set/rep/weight data
- ✏️ Edit past entries directly in the app
- ☁️ Firestore storage per authenticated user

---

🧪 **Currently in Beta**  
Version: **v0.4 Beta**  
Planned improvements include:
- Cardio & superset logging  
- Progress PRs & historical suggestions  
- UI polish and mobile-friendly layout  
- Bug fixes & form validation


## 🚀 Live App

TerraPump will be live on Streamlit Cloud. Link will go here:
https://terrapump.streamlit.app/
*(Make sure you're logged into the right account to access it.)*

---

## 🛠️ Tech Stack

- **Frontend/UI:** Streamlit
- **Auth & DB:** Firebase Authentication + Firestore
- **Data Processing:** pandas, Altair
- **Deployment:** Streamlit Cloud (Flask migration planned post-beta)

---

## 📦 Installation

```bash
# 1. Clone the repo
git clone https://github.com/jaime428/terrapump.git
cd terrapump

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate    # On Windows use venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add Firebase secrets
# - Place your Firebase Admin SDK in: secrets/credentials.json
# - Add your Firebase config to app/firebase_config.py

# 5. Run the app
streamlit run app/dashboard.py


---

### 👤 Developer

**Jaime Cruz**  
📧 jaimecruz428@gmail.com  
🔗 [LinkedIn](https://www.linkedin.com/in/jaimecruz428/)  
🌐 GitHub: [@jaime428](https://github.com/jaime428)

---

### 🛑 Disclaimer

This is a student-built project in early development. Data may not persist between sessions. Please don’t use sensitive personal info. More features and polish coming soon.

---

