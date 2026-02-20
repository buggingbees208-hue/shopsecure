from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime
import os

# ---------------- DATABASE URL ----------------
# Render External URL
DATABASE_URL = "postgresql://security32_user:JvPbCr9N0RXL50jJGKD0lb7aV5XnBQyA@dpg-d6ap7gngi27c73d7s7tg-a.oregon-postgres.render.com/security32"

# ---------------- ENGINE (Updated for Stability) ----------------
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "sslmode": "require",
        "connect_timeout": 30 # Connection waiting time increase pannirukken
    },
    pool_pre_ping=True, # Dead connections-ai auto-va handle pannum
    pool_recycle=300
)

SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine
)

Base = declarative_base()

# ---------------- MODELS ----------------

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    email = Column(String(150), unique=True, nullable=False)
    password = Column(String(255), nullable=False) 
    
    # 🔐 ROLE BASED LOGIN (Admin vs Customer separation)
    role = Column(String(20), default="customer") # 'admin' or 'customer'
    
    failed_logins = Column(Integer, default=0) 
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    orders = relationship("Order", back_populates="owner")
    transactions = relationship("TransactionLog", back_populates="user")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(50), unique=True, index=True)
    product_name = Column(String(150))
    price = Column(Float)
    address = Column(String(255))
    payment_type = Column(String(50))
    status = Column(String(50), default="PENDING")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="orders")
    feedbacks = relationship("Feedback", back_populates="parent_order")
    
    # 🔐 OTP SECURITY (Security Framework Integration)
    otp_code = Column(String(10), nullable=True)
    otp_created_at = Column(DateTime, nullable=True)
    otp_attempts = Column(Integer, default=0)

class ReturnReq(Base):
    __tablename__ = "returns"
    id = Column(Integer, primary_key=True)
    order_id = Column(String(100), ForeignKey("orders.order_id"))
    email = Column(String(150))
    reason = Column(String(150))
    description = Column(Text, nullable=True)
    return_image = Column(String(255))
    similarity = Column(Float)
    decision = Column(String(50))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class TransactionLog(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    email = Column(String(150))
    img_similarity_score = Column(Float)
    severity = Column(String(50))
    risk_score = Column(Integer)
    final_status = Column(String(50))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User", back_populates="transactions")

class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True)
    order_id = Column(String(100), ForeignKey("orders.order_id"))
    email = Column(String(150))
    rating = Column(Integer)
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    parent_order = relationship("Order", back_populates="feedbacks")

# ---------------- CREATE TABLES ----------------
def create_tables():
    Base.metadata.create_all(bind=engine)

# ---------------- DB DEPENDENCY ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

if __name__ == "__main__":
    print("⏳ Connecting to Render Database...")
    try:
        # Tables create aagura munnadi drops pannanum na pannikkalaam
        # Base.metadata.drop_all(bind=engine) 
        create_tables()
        print("✅ Tables created successfully in Render!")
        print("🚀 Ready for Security Framework Integration.")
    except Exception as e:
        print(f"❌ Error: {e}")