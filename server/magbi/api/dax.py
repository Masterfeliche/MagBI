"""The DAX functions MagBI supports, with their signatures, for the measure editor."""

from __future__ import annotations

from fastapi import APIRouter

from magbi.dax.functions import SIGNATURES, UNSUPPORTED

router = APIRouter(tags=["dax"])


@router.get("/dax/functions")
async def list_functions() -> dict[str, list[dict[str, str]]]:
    return {
        "supported": [
            {"name": name, "signature": signature, "description": description}
            for name, (signature, description) in sorted(SIGNATURES.items())
        ],
        "unsupported": [{"name": name.upper(), "advice": advice} for name, advice in sorted(UNSUPPORTED.items())],
    }
