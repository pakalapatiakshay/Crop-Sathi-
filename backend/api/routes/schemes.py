from fastapi import APIRouter
from services import schemes_service

router = APIRouter(prefix="/schemes", tags=["Schemes"])

@router.get("/")
async def get_schemes():
    """
    Fetch the list of available government agriculture schemes.
    """
    schemes = await schemes_service.get_all_schemes()
    return {"success": True, "data": schemes}
