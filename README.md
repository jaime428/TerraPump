# 🏋️ TerraPump

**TerraPump** is a web-based fitness tracking app built with **Streamlit** and **Firebase**, designed to help users log their workouts, track physical progress, and visualize health stats all in one sleek dashboard.

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

## 🚀 Live App

**🔗 Coming Soon**: TerraPump will be live on Streamlit Cloud. Link will go here:


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
