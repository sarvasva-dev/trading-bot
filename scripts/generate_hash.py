import bcrypt
import sys

def generate_hash():
    print("🔐 NSE Bot: Secure Bcrypt Hash Generator")
    print("----------------------------------------")
    password = input("Enter your secret password (e.g., ADMIN_PASSWORD): ")
    if not password:
        print("Error: Password cannot be empty.")
        return

    # Add a pepper if needed, but standard salt is usually enough for this scale.
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    hash_str = hashed.decode('utf-8')
    
    print("\n✅ GENERATED HASH:")
    print("-" * len(hash_str))
    print(hash_str)
    print("-" * len(hash_str))
    print("\nNext Steps:")
    print("1. Copy the hash above.")
    print("2. Open your .env file.")
    print("3. Replace ADMIN_PASSWORD_HASH with this value.")
    print("4. Delete the original ADMIN_PASSWORD (plaintext).")
    print("5. Restart the bot.")

if __name__ == "__main__":
    generate_hash()
