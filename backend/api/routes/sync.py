"""
Handles the offline background-sync queue: when a farmer's device regains
connectivity, the PWA's Service Worker posts every queued action here in one
batch, so nothing captured in the field is lost.
"""

from fastapi import APIRouter

from db.schemas import SyncRequest, SyncResponse, SyncResultItem
from services import ml_service

router = APIRouter(tags=["Offline Sync"])


@router.post("/sync", response_model=SyncResponse)
async def sync_actions(body: SyncRequest):
    results: list[SyncResultItem] = []

    for action in body.actions:
        try:
            if action.type == "crop_recommendation":
                payload = action.payload
                result = ml_service.predict_crop(
                    n=payload["N"], p=payload["P"], k=payload["K"],
                    ph=payload["ph"], rainfall=payload["rainfall"],
                    lat=payload.get("lat"), lon=payload.get("lon"),
                    temperature=payload.get("temperature"), humidity=payload.get("humidity"),
                )
                results.append(SyncResultItem(
                    client_id=action.client_id, type=action.type, success=True, result=result,
                ))
            elif action.type == "disease_detection":
                results.append(SyncResultItem(
                    client_id=action.client_id, type=action.type, success=False,
                    error="disease_detection sync requires multipart image upload; "
                          "queue it against /analyze-disease directly instead of /sync.",
                ))
            else:
                results.append(SyncResultItem(
                    client_id=action.client_id, type=action.type, success=False,
                    error=f"Unknown action type: {action.type}",
                ))
        except Exception as e:
            results.append(SyncResultItem(
                client_id=action.client_id, type=action.type, success=False, error=str(e),
            ))

    return SyncResponse(results=results)
