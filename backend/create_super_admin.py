from app.db.database import db
from app.services.auth_service import hash_password

users_collection = db["users"]

existing_super_admin = users_collection.find_one({
    "role": "super_admin"
})

if existing_super_admin:

    print("Super Admin already exists!")

else:

    name = input("Enter Super Admin Name: ")
    email = input("Enter Super Admin Email: ")
    password = input("Enter Super Admin Password: ")

    hashed_password = hash_password(password)

    super_admin_data = {
        "name": name,
        "email": email,
        "password": hashed_password,
        "role": "super_admin"
    }

    users_collection.insert_one(super_admin_data)

    print("Super Admin created successfully!")