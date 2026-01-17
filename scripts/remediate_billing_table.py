import asyncio
import traceback
from app.db.session import async_session_maker
from sqlalchemy import text
import structlog

logger = structlog.get_logger()

async def ensure_subscription_table():
    async with async_session_maker() as session:
        try:
            # Check if table exists
            result = await session.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'tenant_subscriptions')"))
            if result.scalar():
                print("tenant_subscriptions table already exists")
                # Even if it exists, let's check if it has the required columns
                cols_result = await session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'tenant_subscriptions'"))
                cols = [row[0] for row in cols_result.all()]
                print(f"Existing columns: {cols}")
                return

            print("Creating tenant_subscriptions table manually...")
            # Note: We split into individual statements to handle driver limitations
            statements = [
                """
                CREATE TABLE tenant_subscriptions (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
                    paystack_customer_code VARCHAR(255),
                    paystack_subscription_code VARCHAR(255),
                    paystack_email_token VARCHAR(255),
                    tier VARCHAR(20) NOT NULL DEFAULT 'trial',
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    next_payment_date TIMESTAMP WITH TIME ZONE,
                    canceled_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """,
                "CREATE INDEX idx_tenant_subscriptions_tenant_id ON tenant_subscriptions(tenant_id)"
            ]
            
            for stmt in statements:
                await session.execute(text(stmt))
            
            await session.commit()
            print("Successfully created tenant_subscriptions table")
            
        except Exception as e:
            print(f"Error during table creation: {str(e)}")
            traceback.print_exc()
            await session.rollback()

if __name__ == '__main__':
    asyncio.run(ensure_subscription_table())
