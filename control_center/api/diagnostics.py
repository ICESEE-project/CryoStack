from aiohttp import web

from ..pages.ops import diagnostics_api as _diagnostics_api


async def diagnostics_api(
    request: web.Request,
) -> web.Response:

    return await _diagnostics_api(
        request
    )
