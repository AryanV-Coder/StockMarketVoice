from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from test_single_call import fetch_stock_data, initiate_call

router = APIRouter(tags=["test"])


class SingleCallRequest(BaseModel):
    phone_number: str
    client_name: str


@router.post("/test-single-call")
def test_single_call(request: SingleCallRequest):
    """Fetch stock data for a single client and initiate a call."""
    stock_data = fetch_stock_data(request.phone_number)
    if not stock_data or len(stock_data["rows"]) == 0:
        raise HTTPException(status_code=404, detail="No stock data found for this phone number.")

    call_sid = initiate_call(request.phone_number, request.client_name, stock_data)
    if not call_sid:
        raise HTTPException(status_code=500, detail="Failed to initiate call.")

    return {
        "status": "success",
        "call_sid": call_sid,
        "stocks_found": len(stock_data["rows"]),
    }
