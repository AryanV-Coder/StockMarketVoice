from fastapi import APIRouter
from orchestrate_calls import run

router = APIRouter(tags=["orchestrate"])


@router.post("/orchestrate-calls")
def orchestrate_calls():
    """Fetch all clients from DB and initiate calls to each one."""
    try:
        run()
        return {"status": "success", "message": "All clients processed."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
