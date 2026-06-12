"""Schemas for Stripe billing endpoints (parity with server/api/stripe)."""
from typing import Literal

from pydantic import BaseModel

PlanName = Literal["starter", "pro"]
BillingInterval = Literal["monthly", "yearly"]


class CheckoutRequest(BaseModel):
    planName: PlanName
    billing: BillingInterval = "monthly"
    successUrl: str | None = None
    cancelUrl: str | None = None


class CheckoutResponse(BaseModel):
    url: str
    sessionId: str


class PortalResponse(BaseModel):
    url: str


class CancelRequest(BaseModel):
    immediately: bool = False


class CancelResponse(BaseModel):
    success: bool
    cancelAtPeriodEnd: bool = False


class Invoice(BaseModel):
    id: str
    amount_paid: int
    currency: str
    status: str
    hosted_invoice_url: str | None = None
    created_at: str


class InvoicesResponse(BaseModel):
    invoices: list[Invoice]
