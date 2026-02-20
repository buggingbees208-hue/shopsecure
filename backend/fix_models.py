import os
import joblib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models")

def load_model(filename):
    path = os.path.join(MODEL_DIR, filename)

    if not os.path.exists(path):
        print(f"⚠ Model not found: {filename}")
        return None

    try:
        model = joblib.load(path)
        print(f"✅ Loaded model: {filename}")
        return model
    except Exception as e:
        print(f"❌ Error loading {filename}: {e}")
        return None


# Load all models safely
fraud_isomodel = load_model("fraud_isomodel.pkl")
return_rf_model = load_model("return_fraud_rfmodel.pkl")
category_encoder = load_model("category_encoder.pkl")
return_fraud_model = load_model("return_fraud_model_trained.pkl")
