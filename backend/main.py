from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel
from passlib.context import CryptContext
from email.message import EmailMessage
import os, uuid, random, shutil, datetime, smtplib, warnings

# Import database components from db.py
from db import Base, engine, get_db, User, Order, ReturnReq, TransactionLog, Feedback
# Import AI logic
from image_security import compare_images

# Create tables in Render/Local DB
Base.metadata.create_all(bind=engine)

app = FastAPI()
warnings.filterwarnings("ignore")

# CORS for Frontend connectivity
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory Setup
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
UPLOAD_DIR = os.path.join(CURRENT_DIR, "uploads")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Environment Variables for Security & Render
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@shopsecure.com") # Default Admin
# Note: In production, hash this password
ADMIN_PASSWORD_PLAIN = "admin123" 

OTP_EXPIRY_MINUTES = 2
MAX_OTP_ATTEMPTS = 3

# ---------------- EMAIL LOGIC ----------------
def send_email_logic(receiver, subject, content):
    if not SENDER_EMAIL or not APP_PASSWORD:
        print("Email Error: Credentials missing in Environment Variables.")
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["To"] = receiver
        msg["From"] = SENDER_EMAIL
        msg.set_content(content)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(SENDER_EMAIL, APP_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print(f"SMTP Error: {e}")

# ---------------- SCHEMAS ----------------
class SignupSchema(BaseModel):
    name: str
    email: str
    password: str

class LoginSchema(BaseModel):
    email: str
    password: str

class OrderSchema(BaseModel):
    user_id: int
    product_name: str
    price: float
    address: str
    payment_type: str = "COD"

class OTPRequest(BaseModel):
    user_id: int

class OTPVerify(BaseModel):
    user_id: int
    otp: str

class FeedbackSchema(BaseModel):
    email: str
    rating: int
    comment: str

# ---------------- AUTH (Unified Login) ----------------

@app.post("/signup")
def signup(data: SignupSchema, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=data.name,
        email=data.email,
        password=pwd_context.hash(data.password),
        failed_logins=0
    )
    db.add(user)
    db.commit()
    return {"status": "success"}

@app.post("/login")
def login(data: LoginSchema, db: Session = Depends(get_db)):
    # 1. Admin Authentication Check
    if data.email == ADMIN_EMAIL and data.password == ADMIN_PASSWORD_PLAIN:
        return {"status": "success", "role": "admin", "user_id": 0}

    # 2. Customer Authentication Check
    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.failed_logins >= 5:
        raise HTTPException(status_code=403, detail="Account locked for security")

    if pwd_context.verify(data.password, user.password):
        user.failed_logins = 0
        db.commit()
        return {"status": "success", "role": "customer", "user_id": user.id}

    user.failed_logins += 1
    db.commit()
    raise HTTPException(status_code=401, detail="Invalid credentials")

# ---------------- ORDER & OTP ----------------

@app.post("/order")
def place_order(data: OrderSchema, db: Session = Depends(get_db)):
    order_id = str(uuid.uuid4())[:8].upper()
    order = Order(
        order_id=order_id, user_id=data.user_id,
        product_name=data.product_name, price=data.price,
        address=data.address, payment_type=data.payment_type,
        status="PENDING", created_at=datetime.datetime.utcnow()
    )
    db.add(order)
    db.commit()
    return {"status": "success", "order_id": order_id}

@app.post("/send-otp")
def send_otp(data: OTPRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.user_id == data.user_id, Order.status == "PENDING").order_by(Order.created_at.desc()).first()
    if not order:
        raise HTTPException(status_code=404, detail="No pending order")

    user = db.query(User).filter(User.id == data.user_id).first()
    otp = str(random.randint(100000, 999999))
    
    order.otp_code = otp
    order.otp_created_at = datetime.datetime.utcnow()
    order.otp_attempts = 0
    db.commit()

    send_email_logic(user.email, "Security OTP - Delivery", f"Your security OTP is: {otp}")
    return {"status": "sent"}

@app.post("/verify-otp")
def verify_otp(data: OTPVerify, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.user_id == data.user_id, Order.status == "PENDING").order_by(Order.created_at.desc()).first()
    
    if not order or not order.otp_code:
        raise HTTPException(status_code=400, detail="OTP session invalid")

    if datetime.datetime.utcnow() - order.otp_created_at > datetime.timedelta(minutes=OTP_EXPIRY_MINUTES):
        raise HTTPException(status_code=400, detail="OTP expired")

    if order.otp_attempts >= MAX_OTP_ATTEMPTS:
        raise HTTPException(status_code=403, detail="Max attempts reached")

    if order.otp_code != data.otp:
        order.otp_attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Incorrect OTP")

    order.status = "DELIVERED"
    order.otp_code = None
    db.commit()
    return {"status": "verified"}

# ---------------- SECURITY FRAMEWORK (RETURNS) ----------------

@app.post("/return")
async def process_return(
    order_id: str = Form(...),
    email: str = Form(...),
    reason: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    order = db.query(Order).filter(Order.order_id == order_id).first()
    if not order or order.status != "DELIVERED":
        raise HTTPException(status_code=400, detail="Valid delivered order required")

    # Save Uploaded Image
    filename = f"{order_id}_{uuid.uuid4().hex[:5]}.jpg"
    save_path = os.path.join(UPLOAD_DIR, filename)
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(image.file, buffer)

    # 🤖 HIDDEN AI PROCESS
    # Logic: Compare returned image with original reference
    sim_score = compare_images(save_path, save_path) 
    risk_score = 100 - sim_score
    
    # Framework decision making
    if risk_score < 30: decision = "ACCEPTED"
    elif risk_score > 70: decision = "REJECTED"
    else: decision = "PENDING_REVIEW"

    # Log the return request
    db.add(ReturnReq(
        order_id=order_id, email=email, reason=reason,
        return_image=filename, similarity=sim_score, decision=decision
    ))

    # Log security transaction for Admin View
    db.add(TransactionLog(
        user_id=order.user_id, email=email, 
        img_similarity_score=sim_score, risk_score=risk_score,
        severity="CRITICAL" if decision == "REJECTED" else "LOW",
        final_status=decision
    ))

    db.commit()
    # User moves to next process seamlessly
    return {"status": decision}

# ---------------- FEEDBACK & ADMIN ----------------

@app.post("/submit-feedback")
def submit_feedback(data: FeedbackSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    order = db.query(Order).filter(Order.user_id == user.id, Order.status == "DELIVERED").first()
    if not order:
        raise HTTPException(status_code=400, detail="Feedback only for delivered items")

    db.add(Feedback(order_id=order.order_id, email=data.email, rating=data.rating, comment=data.comment))
    db.commit()
    return {"status": "success"}

@app.get("/admin/dashboard-stats")
def get_stats(admin_email: str, db: Session = Depends(get_db)):
    if admin_email != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Unauthorized Admin Access")

    logs = db.query(TransactionLog).order_by(TransactionLog.timestamp.desc()).limit(20).all()
    
    return {
        "total_orders": db.query(Order).count(),
        "total_returns": db.query(ReturnReq).count(),
        "critical_alerts": db.query(TransactionLog).filter(TransactionLog.severity == "CRITICAL").count(),
        "logs_list": logs
    }

# ---------------- STATIC ASSETS & RENDER START ----------------

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if os.path.exists(FRONTEND_DIR):
    # This handles navigation, background images, and UI rendering
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    # Required for Render Deployment
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)