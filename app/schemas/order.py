"""Pydantic schemas for order requests and responses."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class Customer(BaseModel):
    """Customer recipient information."""

    name: str = Field(..., min_length=1, description="Customer full name")
    phone: str = Field(..., min_length=1, description="Contact phone number")
    address: str = Field(..., min_length=1, description="Delivery destination address")
    city: Optional[str] = Field(None, description="City name")
    state: Optional[str] = Field(None, description="State / Province")
    pincode: Optional[str] = Field(None, description="Postal / ZIP code")
    email: Optional[str] = Field(None, description="Email address")

    model_config = ConfigDict(extra="allow")


class OrderItem(BaseModel):
    """Line item in an order."""

    name: str = Field(..., min_length=1, description="Item name / title")
    quantity: int = Field(..., ge=1, description="Quantity of items, at least 1")
    price: float = Field(..., ge=0.0, description="Unit price, at least 0.0")

    model_config = ConfigDict(extra="allow")


class OrderCreateRequest(BaseModel):
    """Unified payload for creating a shipment order across couriers."""

    order_id: str = Field(..., min_length=1, max_length=64, description="Unique client order ID")
    courier_partner: str = Field(..., min_length=1, description="Target courier partner name")
    customer: Customer = Field(..., description="Customer consignee details")
    items: list[OrderItem] = Field(..., min_length=1, description="List of items in the order")

    model_config = ConfigDict(extra="allow")


class OrderResponse(BaseModel):
    """Unified response returned after order creation."""

    order_id: str
    courier_partner: str
    courier_order_id: Optional[str] = None
    awb_number: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OrderCancelResponse(BaseModel):
    """Response returned upon order cancellation."""

    order_id: str
    status: str

    model_config = ConfigDict(from_attributes=True)
