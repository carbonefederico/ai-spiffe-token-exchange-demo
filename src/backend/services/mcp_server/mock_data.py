demo_profile = {
        "customerId": "cust-1001",
        "name": "Static Demo User",
        "plan": "Northstar Fiber + Mobile Unlimited",
        "devices": [
            {"name": "iPhone 15", "status": "active"},
            {"name": "Fiber Gateway", "status": "online"},
        ],
        "usage": {
            "mobileDataGb": 42.8,
            "homeFiberGb": 812,
            "cycleDay": 18,
        },
    }

customers = {
    "cust-1001": demo_profile,
}

demo_payment = {
        "customerId": "cust-1001",
        "balance": 76.45,
        "currency": "EUR",
        "dueDate": "2026-06-27",
        "autopay": True,
        "recentInvoices": [
            {"month": "2026-06", "amount": 76.45, "status": "open"},
            {"month": "2026-05", "amount": 74.20, "status": "paid"},
        ],
    }

payments = {
    "cust-1001": demo_payment,
}


def customer_profile_for(customer_id: str) -> dict:
    if customer_id in customers:
        return customers[customer_id]
    return {
        **demo_profile,
        "customerId": customer_id,
        "name": f"Demo Customer {customer_id}",
        "source": "default-demo-profile",
    }


def payment_summary_for(customer_id: str) -> dict:
    if customer_id in payments:
        return payments[customer_id]
    return {
        **demo_payment,
        "customerId": customer_id,
        "source": "default-demo-profile",
    }
