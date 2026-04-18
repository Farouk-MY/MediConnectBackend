"""
Migration: Add OTP email verification columns to users table.
- Adds is_verified (boolean, default false)
- Adds otp_code (text, nullable)
- Adds otp_expires_at (timestamp, nullable)
- Sets ALL existing users to is_verified = true
"""
import asyncio
import asyncpg
from app.config import settings


async def run_migration():
    conn = await asyncpg.connect(settings.DATABASE_URL)

    try:
        # Check if is_verified column already exists
        result = await conn.fetchval("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'is_verified'
        """)

        if result:
            print("[INFO] Column 'is_verified' already exists. Skipping column creation.")
        else:
            print("[1/3] Adding is_verified column...")
            await conn.execute("""
                ALTER TABLE users ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT false
            """)

            print("[2/3] Adding otp_code column...")
            await conn.execute("""
                ALTER TABLE users ADD COLUMN otp_code TEXT
            """)

            print("[3/3] Adding otp_expires_at column...")
            await conn.execute("""
                ALTER TABLE users ADD COLUMN otp_expires_at TIMESTAMP
            """)

            print("[OK] Columns added successfully!")

        # Set all existing users to verified
        count = await conn.execute("""
            UPDATE users SET is_verified = true WHERE is_verified = false
        """)
        print(f"[OK] Existing users set to verified: {count}")

        print("[DONE] Migration complete!")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
