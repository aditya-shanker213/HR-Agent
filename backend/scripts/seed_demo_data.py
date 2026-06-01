# backend/scripts/seed_demo_data.py

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

MONGO_URL = "mongodb://localhost:27017"
DB_NAME   = "hr_agent"


async def seed():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # ── Clear existing demo data ───────────────────────────
    await db["users"].delete_many({"user_id": "emp_001"})
    await db["leaves"].delete_many({"user_id": "emp_001"})
    await db["payroll"].delete_many({"user_id": "emp_001"})
    await db["claims"].delete_many({"user_id": "emp_001"})

    # ── Create demo employee ───────────────────────────────
    await db["users"].insert_one({
        "user_id":    "emp_001",
        "name":       "Aditya Kashyap",
        "email":      "aditya.kashyap@giggslab.com",
        "department": "Engineering",
        "role":       "employee",
        "manager_id": "mgr_001",
        "leave_balance": {
            "casual":    10,
            "sick":      7,
            "earned":    14,
            "emergency": 3,
        },
        "joining_date": datetime(2023, 6, 1),
        "is_active":    True,
        "created_at":   datetime.utcnow(),
    })
    print("✓ Employee emp_001 created")

    # ── Create payslips ────────────────────────────────────
    months = [
        ("January",  "2026", 85000, 12000, 9500),
        ("February", "2026", 85000, 12000, 9500),
        ("March",    "2026", 87000, 13000, 9800),
        ("April",    "2026", 87000, 13000, 9800),
    ]

    for month, year, basic, allowance, deductions in months:
        await db["payroll"].insert_one({
            "payroll_id":   f"PAY-{month[:3].upper()}-2026",
            "user_id":      "emp_001",
            "month":        month,
            "year":         year,
            "basic_salary": basic,
            "allowances":   allowance,
            "deductions": {
                "pf":               basic * 0.12,
                "tax":              deductions - (basic * 0.12),
                "professional_tax": 200,
                "other":            0,
            },
            "net_salary":  basic + allowance - deductions,
            "paid_on":     datetime(2025, list(["January","February","March","April"]).index(month)+1, 28),
            "created_at":  datetime.utcnow(),
        })
    print("✓ Payslips created for Jan–Apr 2026")

    # ── Create a sample past leave ─────────────────────────
    await db["leaves"].insert_one({
        "leave_id":   "LV-DEMO-001",
        "user_id":    "emp_001",
        "leave_type": "casual",
        "num_days":   2,
        "start_date": "March 10",
        "end_date":   "March 11",
        "reason":     "Personal work",
        "status":     "approved",
        "applied_at": datetime(2026, 3, 8),
        "reviewed_by": "mgr_001",
        "reviewed_at": datetime(2026, 3, 9),
    })
    print("✓ Sample leave history created")

    # ── Create a sample past claim ─────────────────────────
    await db["claims"].insert_one({
        "claim_id":     "CL-DEMO-001",
        "user_id":      "emp_001",
        "claim_type":   "travel",
        "amount":       2500,
        "currency":     "INR",
        "description":  "Client visit — Mumbai",
        "status":       "approved",
        "submitted_at": datetime(2026, 3, 15),
        "reviewed_by":  "mgr_001",
        "reviewed_at":  datetime(2026, 3, 16),
    })
    print("✓ Sample claim created")

    client.close()
    print("\n✅ Demo data seeded successfully")
    print("   User ID: emp_001")
    print("   Test with: 'How many leaves do I have?'")
    print("             'Show my March salary slip'")
    print("             'Apply 2 days casual leave from Monday'")


if __name__ == "__main__":
    asyncio.run(seed())